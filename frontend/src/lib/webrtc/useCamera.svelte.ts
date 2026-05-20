// Native browser-side camera enumeration + getUserMedia, with proper
// {exact: id} constraints so device picks are honoured.

export interface CameraDevice {
  deviceId: string;
  label: string;
}

export const cameraStore = $state<{
  devices: CameraDevice[];
  selectedDeviceId: string | null;
  stream: MediaStream | null;
  error: string | null;
}>({
  devices: [],
  selectedDeviceId: null,
  stream: null,
  error: null,
});

export async function refreshDevices(): Promise<void> {
  try {
    // Trigger a permission request if we don't have one — without it,
    // enumerateDevices returns blank labels.
    await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      .then(s => s.getTracks().forEach(t => t.stop()))
      .catch(() => {});

    const all = await navigator.mediaDevices.enumerateDevices();
    cameraStore.devices = all
      .filter(d => d.kind === 'videoinput')
      .map(d => ({
        deviceId: d.deviceId,
        label: d.label || `Camera ${d.deviceId.slice(0, 6)}`,
      }));
    if (!cameraStore.selectedDeviceId && cameraStore.devices.length > 0) {
      cameraStore.selectedDeviceId = cameraStore.devices[0].deviceId;
    }
  } catch (err: any) {
    cameraStore.error = err.message;
  }
}

export async function startCamera(
  deviceId: string, width: number, height: number,
): Promise<MediaStream> {
  if (cameraStore.stream) {
    cameraStore.stream.getTracks().forEach(t => t.stop());
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      deviceId: { exact: deviceId },
      width: { ideal: width },
      height: { ideal: height },
      frameRate: { ideal: 30 },
    },
    audio: false,
  });
  cameraStore.stream = stream;
  cameraStore.selectedDeviceId = deviceId;
  cameraStore.error = null;
  return stream;
}

export function stopCamera(): void {
  if (cameraStore.stream) {
    cameraStore.stream.getTracks().forEach(t => t.stop());
    cameraStore.stream = null;
  }
}
