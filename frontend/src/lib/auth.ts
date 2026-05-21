const TOKEN_KEY = "agent33.token";
const API_KEY = "agent33.apiKey";

export function getSavedToken(): string {
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}

export function saveToken(token: string): void {
  if (token.trim() === "") {
    window.localStorage.removeItem(TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, token.trim());
}

export function getSavedApiKey(): string {
  return window.localStorage.getItem(API_KEY) ?? "";
}

export function saveApiKey(apiKey: string): void {
  if (apiKey.trim() === "") {
    window.localStorage.removeItem(API_KEY);
    return;
  }
  window.localStorage.setItem(API_KEY, apiKey.trim());
}
