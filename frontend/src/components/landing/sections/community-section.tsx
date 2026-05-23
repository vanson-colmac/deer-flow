"use client";

import { LinkedInLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { AuroraText } from "@/components/ui/aurora-text";
import { Button } from "@/components/ui/button";

import { Section } from "../section";

export function CommunitySection() {
  return (
    <Section
      title={
        <AuroraText colors={["#60A5FA", "#A5FA60", "#A560FA"]}>
          Join the Community
        </AuroraText>
      }
      subtitle="Connect with me on LinkedIn to shape the future of Marketior.AI. Collaborate, innovate, and make impacts."
    >
      <div className="flex justify-center">
        <Button className="text-xl" size="lg" asChild>
          <Link
            href="https://www.linkedin.com/in/evolvewithvansh/"
            target="_blank"
            rel="noopener noreferrer"
          >
            <LinkedInLogoIcon />
            Connect on LinkedIn
          </Link>
        </Button>
      </div>
    </Section>
  );
}
