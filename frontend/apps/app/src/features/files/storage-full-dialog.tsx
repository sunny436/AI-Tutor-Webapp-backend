"use client";

import { Button } from "@v1/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@v1/ui/dialog";
import Link from "next/link";
import { useEffect, useState } from "react";

import { formatBytes, listFiles } from "@/lib/api/files";
import type { FileUsage } from "@/lib/api/types";

/** Shown when an upload is refused because the student's storage is full. Nothing is deleted for them. */
export function StorageFullDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [usage, setUsage] = useState<FileUsage | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    listFiles()
      .then((list) => alive && setUsage(list.usage))
      .catch(() => alive && setUsage(null));
    return () => {
      alive = false;
    };
  }, [open]);

  const quota = formatBytes(usage?.quotaBytes ?? 100 * 1024 * 1024);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Storage full</DialogTitle>
          <DialogDescription>
            {usage ? `You've used ${formatBytes(usage.usedBytes)} of ${quota}. ` : ""}
            Free up storage to upload another file.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button asChild onClick={() => onOpenChange(false)}>
            <Link href="/library">Open File Library</Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
