"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import Galaxy from "@/components/ui/galaxy";
import { WordRotate } from "@/components/ui/word-rotate";
import { cn } from "@/lib/utils";

export function Hero({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-full flex-col items-center justify-center",
        className,
      )}
    >
      <div className="absolute inset-0 z-0 bg-black/40">
        <Galaxy
          mouseRepulsion={false}
          starSpeed={0.2}
          density={0.6}
          glowIntensity={0.35}
          twinkleIntensity={0.3}
          speed={0.5}
        />
      </div>
      <FlickeringGrid
        className="absolute inset-0 z-0 translate-y-8 mask-[url(/images/marketior-logo.svg)] mask-size-[100vw] mask-center mask-no-repeat md:mask-size-[72vh]"
        squareSize={4}
        gridGap={4}
        color={"#0066FF"}
        maxOpacity={0.4}
        flickerChance={0.25}
      />
      <div className="container-md relative z-10 mx-auto flex h-screen flex-col items-center justify-center">
        <h1 className="flex items-center gap-2 text-4xl font-bold md:text-6xl">
          <WordRotate
            words={[
              "Deep Research",
              "Collect Data",
              "Analyze Data",
              "Generate Webpages",
              "Vibe Coding",
              "Generate Slides",
              "Generate Images",
              "Generate Podcasts",
              "Generate Videos",
              "Generate Songs",
              "Organize Emails",
              "Do Anything",
              "Learn Anything",
            ]}
          />{" "}
          <div>
            with <span className="text-blue-400">Marketior.AI</span>
          </div>
        </h1>
        <p className="text-muted-foreground mt-8 scale-105 text-center text-2xl text-shadow-sm">
          A.I For People — An intelligent platform that researches, codes, and
          creates.
          <br />
          With sandboxes, memories, tools, skills and subagents, it handles
          <br />
          different levels of tasks that could take minutes to hours.
        </p>
        <Link href="/workspace">
          <Button
            className="mt-8 rounded-full bg-blue-600 px-8 py-6 text-lg font-medium text-white shadow-lg shadow-blue-500/20 transition-all hover:scale-105 hover:bg-blue-500 hover:shadow-blue-500/40"
          >
            Launch Dashboard
            <ChevronRightIcon className="ml-2 size-5" />
          </Button>
        </Link>
      </div>
    </div>
  );
}
