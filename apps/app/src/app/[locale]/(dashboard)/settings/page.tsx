"use client";

import { ChangePasswordCard } from "@/components/change-password-card";
import { SessionsCard } from "@/components/sessions-card";
import { useScopedI18n } from "@/locales/client";
import { useAuthActions } from "@convex-dev/auth/react";
import { useForm } from "@tanstack/react-form";
import { zodValidator } from "@tanstack/zod-form-adapter";
import { api } from "@v1/backend/convex/_generated/api";
import type { Id } from "@v1/backend/convex/_generated/dataModel";
import * as validators from "@v1/backend/convex/utils/validators";
import { Avatar, AvatarFallback, AvatarImage } from "@v1/ui/avatar";
import { Button } from "@v1/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@v1/ui/card";
import { Input } from "@v1/ui/input";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { UploadInput } from "@v1/ui/upload-input";
import { useDoubleCheck } from "@v1/ui/utils";
import type { UploadFileResponse } from "@xixixao/uploadstuff/react";
import { useAction, useMutation, useQuery } from "convex/react";
import { Upload } from "lucide-react";

export default function DashboardSettings() {
  const t = useScopedI18n("settings");
  const user = useQuery(api.users.getUser);
  const { signOut } = useAuthActions();
  const updateUserImage = useMutation(api.users.updateUserImage);
  const updateUsername = useMutation(api.users.updateUsername);
  const removeUserImage = useMutation(api.users.removeUserImage);
  const generateUploadUrl = useMutation(api.users.generateUploadUrl);
  const deleteCurrentUserAccount = useAction(
    api.users.deleteCurrentUserAccount,
  );
  const { doubleCheck, getButtonProps } = useDoubleCheck();

  const handleUpdateUserImage = (uploaded: UploadFileResponse[]) => {
    return updateUserImage({
      imageId: (uploaded[0]?.response as { storageId: Id<"_storage"> })
        .storageId,
    });
  };

  const handleDeleteAccount = async () => {
    await deleteCurrentUserAccount();
    signOut();
  };

  const usernameForm = useForm({
    validatorAdapter: zodValidator(),
    defaultValues: {
      username: user?.username,
    },
    onSubmit: async ({ value }) => {
      await updateUsername({ username: value.username || "" });
    },
  });

  if (!user) {
    // Was `return null`, so the first paint of the account page was a blank
    // area under the chrome with nothing to say it was still arriving. Shaped
    // to the four panels below so the layout does not jump when they land.
    return (
      <SkeletonGroup
        label="Loading your settings"
        className="flex h-full w-full flex-col gap-6"
      >
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-44 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
      </SkeletonGroup>
    );
  }

  return (
    <div className="flex h-full w-full flex-col gap-6">
      {/* Avatar */}
      <Card variant="raised">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <CardTitle as="h2">{t("avatar.title")}</CardTitle>
            <CardDescription>{t("avatar.description")}</CardDescription>
          </div>
          <label
            htmlFor="avatar_field"
            className="group relative flex shrink-0 cursor-pointer overflow-hidden rounded-full transition active:scale-95"
          >
            {/* The Avatar primitive rather than a raw img plus a gradient div:
                it swaps to the fallback when the URL 404s, and the fallback is
                the account initial on brand-soft rather than a
                lime-400 / cyan-300 / blue-500 blob — the last raw-palette
                gradient in the product, and one that identified nobody. */}
            <Avatar className="h-20 w-20">
              <AvatarImage
                src={user.avatarUrl ?? undefined}
                alt={user.username ?? user.email}
              />
              <AvatarFallback className="bg-brand-soft font-display text-2xl font-semibold text-brand">
                {(user.username ?? user.email ?? "?").charAt(0).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            {/* bg-primary/40 was a dark-mode bug: --primary is the near-black
                TEXT colour, which inverts to near-WHITE, so this scrim painted
                a white veil with a pale icon sitting on it. */}
            <div className="absolute z-10 hidden h-full w-full items-center justify-center bg-foreground/50 group-hover:flex">
              <Upload className="h-6 w-6 text-background" />
            </div>
          </label>
          <UploadInput
            id="avatar_field"
            type="file"
            accept="image/*"
            className="peer sr-only"
            required
            tabIndex={user ? -1 : 0}
            generateUploadUrl={generateUploadUrl}
            onUploadComplete={handleUpdateUserImage}
          />
        </CardHeader>
        <CardFooter className="justify-between rounded-b-xl bg-surface">
          <p className="text-sm text-text-secondary">{t("avatar.uploadHint")}</p>
          {user.avatarUrl && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                removeUserImage({});
              }}
            >
              {t("avatar.resetButton")}
            </Button>
          )}
        </CardFooter>
      </Card>

      {/* Username */}
      <form
        className="flex w-full flex-col rounded-xl border border-border bg-card text-card-foreground elev-1"
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          usernameForm.handleSubmit();
        }}
      >
        <CardHeader>
          <CardTitle as="h2">Your Username</CardTitle>
          <CardDescription>
            This is your username. It will be displayed on your profile.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <usernameForm.Field
            name="username"
            validators={{
              onSubmit: validators.username,
            }}
            // biome-ignore lint/correctness/noChildrenProp: <explanation>
            children={(field) => (
              <Input
                placeholder="Username"
                aria-label="Username"
                autoComplete="off"
                required
                value={field.state.value}
                onBlur={field.handleBlur}
                onChange={(e) => field.handleChange(e.target.value)}
                // w-full sm:w-80 — at 375px this card has about 295px of inner
                // width and a flat w-80 is 320px, so the field overflowed its
                // own card by 25px on the narrowest common phone.
                className={`w-full bg-transparent sm:w-80 ${
                  field.state.meta?.errors.length > 0 &&
                  "border-destructive focus-visible:ring-destructive"
                }`}
              />
            )}
          />
          {usernameForm.state.fieldMeta.username?.errors.length > 0 && (
            // The dark:text-destructive-foreground override made errors
            // near-white in dark mode. --destructive is already tuned for both
            // themes, so the override was fighting it.
            <p className="text-sm text-destructive">
              {usernameForm.state.fieldMeta.username?.errors.join(" ")}
            </p>
          )}
        </CardContent>
        <CardFooter className="justify-between rounded-b-xl bg-surface">
          <p className="text-sm text-text-secondary">
            Please use 32 characters at maximum.
          </p>
          <Button type="submit" size="sm">
            Save
          </Button>
        </CardFooter>
      </form>

      {/* Security: password + active sessions */}
      <ChangePasswordCard />
      <SessionsCard />

      {/* Delete Account */}
      <Card variant="raised" className="border-destructive/40">
        <CardHeader>
          <CardTitle as="h2">{t("deleteAccount.title")}</CardTitle>
          <CardDescription>{t("deleteAccount.description")}</CardDescription>
        </CardHeader>
        <CardFooter className="justify-between gap-4 rounded-b-xl border-destructive/20 bg-destructive/10">
          <p className="text-sm text-text-secondary">
            {t("deleteAccount.warning")}
          </p>
          <Button
            size="sm"
            variant="destructive"
            {...getButtonProps({
              onClick: doubleCheck ? handleDeleteAccount : undefined,
            })}
          >
            {doubleCheck
              ? t("deleteAccount.confirmButton")
              : t("deleteAccount.deleteButton")}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
