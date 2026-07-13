import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from marketior.config.app_config import AppConfig, reload_app_config

router = APIRouter(prefix="/api", tags=["models"])

logger = logging.getLogger(__name__)


class ModelResponse(BaseModel):
    """Response model for model information."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")


class TokenUsageResponse(BaseModel):
    """Token usage display configuration."""

    enabled: bool = Field(default=False, description="Whether token usage display is enabled")


class ModelsListResponse(BaseModel):
    """Response model for listing all models."""

    models: list[ModelResponse]
    token_usage: TokenUsageResponse


class ModelCreateRequest(BaseModel):
    """Request body for creating / registering a new LLM model."""

    name: str = Field(..., description="Unique identifier for the model (e.g. 'gpt-4o-custom')")
    model: str = Field(..., description="Actual provider model identifier (e.g. 'gpt-4o')")
    display_name: str | None = Field(None, description="Human-readable display name")
    description: str | None = Field(None, description="Short description of the model")
    use: str = Field(
        default="langchain_openai:ChatOpenAI",
        description="Class path of the model provider (e.g. 'langchain_openai:ChatOpenAI')",
    )
    api_key: str | None = Field(None, description="API key (stored in config.yaml; use $ENV_VAR syntax for env references)")
    base_url: str | None = Field(None, description="Custom base URL for the model endpoint")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")
    request_timeout: float | None = Field(None, description="Request timeout in seconds")
    max_retries: int | None = Field(None, description="Maximum number of retries")


class ModelUpdateRequest(BaseModel):
    """Request body for updating an existing LLM model."""

    model: str | None = Field(None, description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable display name")
    description: str | None = Field(None, description="Short description")
    use: str | None = Field(None, description="Class path of the model provider")
    api_key: str | None = Field(None, description="API key")
    base_url: str | None = Field(None, description="Custom base URL")
    supports_thinking: bool | None = Field(None, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool | None = Field(None, description="Whether model supports reasoning effort")
    request_timeout: float | None = Field(None, description="Request timeout in seconds")
    max_retries: int | None = Field(None, description="Maximum number of retries")


# ---------------------------------------------------------------------------
# Helpers for config.yaml read/write
# ---------------------------------------------------------------------------


def _resolve_config_path() -> Path:
    """Resolve the active config.yaml path."""
    return AppConfig.resolve_config_path()


def _read_config_data() -> dict:
    """Read the raw YAML config as a dict."""
    config_path = _resolve_config_path()
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_config_data(data: dict) -> None:
    """Write the raw dict back to config.yaml."""
    config_path = _resolve_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _model_dict_from_request(req: ModelCreateRequest) -> dict:
    """Build a model dict entry suitable for config.yaml from a create request."""
    entry: dict = {
        "name": req.name,
        "display_name": req.display_name or req.name,
        "use": req.use,
        "model": req.model,
    }
    if req.api_key:
        entry["api_key"] = req.api_key
    if req.base_url:
        entry["base_url"] = req.base_url
    if req.description:
        entry["description"] = req.description
    if req.supports_thinking:
        entry["supports_thinking"] = True
    if req.supports_reasoning_effort:
        entry["supports_reasoning_effort"] = True
    if req.request_timeout is not None:
        entry["request_timeout"] = req.request_timeout
    if req.max_retries is not None:
        entry["max_retries"] = req.max_retries
    return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models(config: AppConfig = Depends(get_config)) -> ModelsListResponse:
    """List all available models from configuration.

    Returns model information suitable for frontend display,
    excluding sensitive fields like API keys and internal configuration.

    Returns:
        A list of all configured models with their metadata and token usage display settings.
    """
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
        )
        for model in config.models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(model_name: str, config: AppConfig = Depends(get_config)) -> ModelResponse:
    """Get a specific model by name.

    Args:
        model_name: The unique name of the model to retrieve.

    Returns:
        Model information if found.

    Raises:
        HTTPException: 404 if model not found.
    """
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )


@router.post(
    "/models",
    response_model=ModelResponse,
    status_code=201,
    summary="Create Model",
    description="Register a new LLM model configuration and persist it to config.yaml.",
)
async def create_model(request: ModelCreateRequest, config: AppConfig = Depends(get_config)) -> ModelResponse:
    """Create a new model configuration.

    Adds the model to config.yaml and reloads the runtime config so
    the new model is immediately available in the chat input selector.

    Args:
        request: Model creation payload.

    Returns:
        The newly created model metadata.

    Raises:
        HTTPException: 409 if a model with the same name already exists.
    """
    # Check for duplicate name
    if config.get_model_config(request.name) is not None:
        raise HTTPException(status_code=409, detail=f"Model '{request.name}' already exists")

    try:
        config_data = _read_config_data()
        models_list: list = config_data.setdefault("models", [])
        models_list.append(_model_dict_from_request(request))
        _write_config_data(config_data)
        reload_app_config()

        logger.info("Created model '%s' in config.yaml", request.name)
        return ModelResponse(
            name=request.name,
            model=request.model,
            display_name=request.display_name or request.name,
            description=request.description,
            supports_thinking=request.supports_thinking,
            supports_reasoning_effort=request.supports_reasoning_effort,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create model '%s': %s", request.name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create model: {e}")


@router.put(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Update Model",
    description="Update an existing LLM model configuration in config.yaml.",
)
async def update_model(
    model_name: str,
    request: ModelUpdateRequest,
    config: AppConfig = Depends(get_config),
) -> ModelResponse:
    """Update an existing model configuration.

    Only fields explicitly provided in the request body are updated;
    omitted fields retain their current values.

    Args:
        model_name: The model to update.
        request: Update payload.

    Returns:
        The updated model metadata.

    Raises:
        HTTPException: 404 if model not found.
    """
    if config.get_model_config(model_name) is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    try:
        config_data = _read_config_data()
        models_list: list = config_data.get("models", [])

        # Find the existing entry by name
        target_idx: int | None = None
        for idx, entry in enumerate(models_list):
            if entry.get("name") == model_name:
                target_idx = idx
                break

        if target_idx is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found in config file")

        existing = models_list[target_idx]
        fields_set = request.model_fields_set

        if "model" in fields_set and request.model is not None:
            existing["model"] = request.model
        if "display_name" in fields_set and request.display_name is not None:
            existing["display_name"] = request.display_name
        if "description" in fields_set:
            existing["description"] = request.description
        if "use" in fields_set and request.use is not None:
            existing["use"] = request.use
        if "api_key" in fields_set and request.api_key is not None:
            existing["api_key"] = request.api_key
        if "base_url" in fields_set and request.base_url is not None:
            existing["base_url"] = request.base_url
        if "supports_thinking" in fields_set and request.supports_thinking is not None:
            existing["supports_thinking"] = request.supports_thinking
        if "supports_reasoning_effort" in fields_set and request.supports_reasoning_effort is not None:
            existing["supports_reasoning_effort"] = request.supports_reasoning_effort
        if "request_timeout" in fields_set and request.request_timeout is not None:
            existing["request_timeout"] = request.request_timeout
        if "max_retries" in fields_set and request.max_retries is not None:
            existing["max_retries"] = request.max_retries

        models_list[target_idx] = existing
        _write_config_data(config_data)
        reload_app_config()

        logger.info("Updated model '%s' in config.yaml", model_name)
        return ModelResponse(
            name=existing.get("name", model_name),
            model=existing.get("model", ""),
            display_name=existing.get("display_name"),
            description=existing.get("description"),
            supports_thinking=existing.get("supports_thinking", False),
            supports_reasoning_effort=existing.get("supports_reasoning_effort", False),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update model '%s': %s", model_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update model: {e}")


@router.delete(
    "/models/{model_name}",
    status_code=204,
    summary="Delete Model",
    description="Remove an LLM model configuration from config.yaml.",
)
async def delete_model(model_name: str, config: AppConfig = Depends(get_config)) -> None:
    """Delete a model from config.yaml and reload the runtime config.

    Args:
        model_name: The model to remove.

    Raises:
        HTTPException: 404 if model not found.
    """
    if config.get_model_config(model_name) is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    try:
        config_data = _read_config_data()
        models_list: list = config_data.get("models", [])
        original_count = len(models_list)
        config_data["models"] = [m for m in models_list if m.get("name") != model_name]

        if len(config_data["models"]) == original_count:
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found in config file")

        _write_config_data(config_data)
        reload_app_config()

        logger.info("Deleted model '%s' from config.yaml", model_name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete model '%s': %s", model_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {e}")
