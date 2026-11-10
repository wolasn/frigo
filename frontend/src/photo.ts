/** Photos pour l'analyse : tout reste en mémoire dans la page, rien n'est enregistré sur l'appareil. */

export type CapturedPhoto = { id: string; preview: string; mediaType: string; data: string };

const MAX_SIDE = 1600; // assez pour lire une date sur un emballage, léger à envoyer
const QUALITY = 0.85;
let counter = 0; // crypto.randomUUID n'existe qu'en contexte sécurisé : absent sur http://192.168.x.x

function newId(): string {
  counter += 1;
  return `photo-${Date.now()}-${counter}`;
}

function canvasToPhoto(canvas: HTMLCanvasElement): CapturedPhoto {
  const dataUrl = canvas.toDataURL("image/jpeg", QUALITY);
  return { id: newId(), preview: dataUrl, mediaType: "image/jpeg", data: dataUrl.slice(dataUrl.indexOf(",") + 1) };
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
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    try {
      return canvasToPhoto(drawScaled(bitmap, bitmap.width, bitmap.height));
    } finally {
      bitmap.close();
    }
  } catch {
    return photoFromImageElement(file); // navigateurs sans createImageBitmap (ou sans ses options)
  }
}

/** Secours : décodage par une balise image, qui applique aussi l'orientation EXIF. */
async function photoFromImageElement(file: File): Promise<CapturedPhoto> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return canvasToPhoto(drawScaled(image, image.naturalWidth, image.naturalHeight));
  } finally {
    URL.revokeObjectURL(url);
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
