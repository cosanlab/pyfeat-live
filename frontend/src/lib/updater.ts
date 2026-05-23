// Thin wrapper around @tauri-apps/plugin-updater. Holds the resolved
// Update object privately between the check and the install so callers
// don't have to thread it through their UI state.
//
// The pattern mirrors what works in our two other Tauri apps
// (hyperstudy-bridge, flowmail): one module owns the lifecycle —
// check → download+install → relaunch — and exposes three async
// functions that map to those three steps.

import { check, type Update, type DownloadEvent } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';

let pendingUpdate: Update | null = null;

export type UpdateCheckResult =
  | { available: true; version: string; currentVersion: string; body: string; date: string | undefined }
  | { available: false; error?: string };

export async function checkForUpdate(): Promise<UpdateCheckResult> {
  try {
    const update = await check();
    if (update) {
      pendingUpdate = update;
      return {
        available: true,
        version: update.version,
        currentVersion: update.currentVersion,
        body: update.body ?? '',
        date: update.date,
      };
    }
    pendingUpdate = null;
    return { available: false };
  } catch (err: unknown) {
    pendingUpdate = null;
    return { available: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export type InstallProgress =
  | { phase: 'started'; contentLength: number }
  | { phase: 'downloading'; downloaded: number; contentLength: number; percent: number }
  | { phase: 'finished' };

export async function downloadAndInstallUpdate(
  onProgress?: (p: InstallProgress) => void,
): Promise<void> {
  if (!pendingUpdate) throw new Error('No pending update — call checkForUpdate first');

  let downloaded = 0;
  let contentLength = 0;

  await pendingUpdate.downloadAndInstall((event: DownloadEvent) => {
    switch (event.event) {
      case 'Started':
        contentLength = event.data.contentLength ?? 0;
        onProgress?.({ phase: 'started', contentLength });
        break;
      case 'Progress':
        downloaded += event.data.chunkLength;
        onProgress?.({
          phase: 'downloading',
          downloaded,
          contentLength,
          percent: contentLength > 0 ? Math.round((downloaded / contentLength) * 100) : 0,
        });
        break;
      case 'Finished':
        onProgress?.({ phase: 'finished' });
        break;
    }
  });

  pendingUpdate = null;
}

export async function relaunchApp(): Promise<void> {
  await relaunch();
}
