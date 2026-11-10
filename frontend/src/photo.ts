/** Photos pour l'analyse : tout reste en mémoire dans la page, rien n'est enregistré sur l'appareil. */

export type CapturedPhoto = { id: string; preview: string; mediaType: string; data: string };

const MAX_SIDE = 1600; // assez pour lire une date sur un emballage, léger à envoyer
const QUALITY = 0.85;

function canvasToPhoto(canvas: HTMLCanvasElement): CapturedPhoto {
  const dataUrl = canvas.toDataURL("image/jpeg", QUALITY);
  return { id: crypto.randomUUID(), preview: dataUrl, mediaType: "image/jpeg", data: dataUrl.slice(dataUrl.indexOf(",") + 1) };
}

function drawScaled(source: CanvasImageSource, width: number, height: number): HTMLCanvasElement {
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext("2d")!.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

/** Photo choisie dans les fichiers : redressée (orientation EXIF), réduite, convertie en JPEG. */
export async function photoFromFile(file: File): Promise<CapturedPhoto> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    return canvasToPhoto(drawScaled(bitmap, bitmap.width, bitmap.height));
  } finally {
    bitmap.close();
  }
}

/** Image courante de la caméra intégrée. */
export function photoFromVideo(video: HTMLVideoElement): CapturedPhoto {
  return canvasToPhoto(drawScaled(video, video.videoWidth, video.videoHeight));
}

/** La caméra intégrée à la page n'est possible qu'en contexte sécurisé (https, ou localhost). */
export function canUseLiveCamera(): boolean {
  return window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
}
