import { rpc } from './rpc';

const players = new Set<HTMLAudioElement>();
export function registerAudio(player: HTMLAudioElement) {
  players.add(player);
  return () => {
    player.pause();
    players.delete(player);
  };
}
export function claimAudio(player: HTMLAudioElement) {
  for (const other of players) if (other !== player) other.pause();
}
export function stopAudioFocus() {
  for (const player of players) {
    player.pause();
    player.currentTime = 0;
  }
}
export async function audioUrl(assetId: string) {
  const result = await rpc('audio.read', { asset_id: assetId });
  const bytes = Uint8Array.from(atob(result.content_b64), (char) => char.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes], { type: result.mime_type }));
}
