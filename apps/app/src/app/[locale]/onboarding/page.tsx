"use client";

import { useForm } from "@tanstack/react-form";
import { zodValidator } from "@tanstack/zod-form-adapter";
import { api } from "@v1/backend/convex/_generated/api";
import * as validators from "@v1/backend/convex/utils/validators";
import { Button } from "@v1/ui/button";
import { Input } from "@v1/ui/input";
import { useMutation, useQuery } from "convex/react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useFormStatus } from "react-dom";

export default function OnboardingUsername() {
  const user = useQuery(api.users.getUser);
  const updateUsername = useMutation(api.users.updateUsername);
  const router = useRouter();

  const { pending } = useFormStatus();

  const form = useForm({
    validatorAdapter: zodValidator(),
    defaultValues: {
      username: "",
    },
    onSubmit: async ({ value }) => {
      await updateUsername({
        username: value.username,
      });
    },
  });

  useEffect(() => {
    if (!user) {
      return;
    }
    if (user?.username) {
      router.push("/");
    }
  }, [user]);

  if (!user) {
    return null;
  }

  return (
    <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-6">
      <div className="flex flex-col items-center gap-2">
        {/* A 60px waving-hand emoji was the largest element on the first screen
            after signup. Emoji render differently on every platform, carry no
            brand, and cannot be styled — the h1 does this job better. */}
        <h1 className="text-center font-display text-2xl font-semibold tracking-tight text-foreground">
          Welcome
        </h1>
        <p className="text-center text-sm leading-relaxed text-text-secondary">
          Choose a username. It&apos;s the only thing we need before you start —
          everything else the assistant learns from what you tell it.
        </p>
      </div>
      <form
        className="flex w-full flex-col items-start gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          form.handleSubmit();
        }}
      >
        <div className="flex w-full flex-col gap-1.5">
          <label htmlFor="username" className="sr-only">
            Username
          </label>
          <form.Field
            name="username"
            validators={{
              onSubmit: validators.username,
            }}
            // biome-ignore lint/correctness/noChildrenProp: tanstack best practice
            children={(field) => (
              <Input
                placeholder="Username"
                autoComplete="off"
                required
                value={field.state.value}
                onBlur={field.handleBlur}
                onChange={(e) => field.handleChange(e.target.value)}
                className={`bg-transparent ${
                  field.state.meta?.errors.length > 0 &&
                  "border-destructive focus-visible:ring-destructive"
                }`}
              />
            )}
          />
        </div>

        <div className="flex flex-col">
          {form.state.fieldMeta.username?.errors.length > 0 && (
            <span className="mb-2 text-sm text-destructive dark:text-destructive-foreground">
              {form.state.fieldMeta.username?.errors.join(" ")}
            </span>
          )}
        </div>

        <Button type="submit" className="mt-1 w-full">
          {pending ? (
            <>
              <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            "Continue"
          )}
        </Button>
      </form>

      <p className="text-center text-xs leading-relaxed text-text-secondary">
        You can change this at any time in settings.
      </p>
    </div>
  );
}
