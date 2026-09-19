import type { UserProfile, UserProfileInput } from '../types';
import { api, USE_MOCK } from './client';
import { MOCK_PROFILE } from './mock';

export async function saveProfile(input: UserProfileInput): Promise<{ user_id: string }> {
  if (USE_MOCK) return { user_id: MOCK_PROFILE.user_id };
  return api.put<{ user_id: string }>('/profile', input);
}

export async function fetchProfile(): Promise<UserProfile> {
  if (USE_MOCK) return MOCK_PROFILE;
  return api.get<UserProfile>('/profile');
}
