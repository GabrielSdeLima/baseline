export function getUserId(): string {
  return localStorage.getItem('baseline_user_id') ?? '';
}

export function setUserId(id: string): void {
  localStorage.setItem('baseline_user_id', id);
}
