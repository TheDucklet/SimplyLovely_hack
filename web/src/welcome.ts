export const WELCOME_STORAGE_KEY = 'geostart.welcome.seen';
const SEEN = '1';

export interface WelcomeStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function browserStorage(): WelcomeStorage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function welcomeSeen(storage: WelcomeStorage | undefined): boolean {
  try {
    return storage?.getItem(WELCOME_STORAGE_KEY) === SEEN;
  } catch {
    return false;
  }
}

export function markWelcomeSeen(storage: WelcomeStorage | undefined): void {
  try {
    storage?.setItem(WELCOME_STORAGE_KEY, SEEN);
  } catch {
    return;
  }
}
