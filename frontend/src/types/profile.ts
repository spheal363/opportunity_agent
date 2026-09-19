/** backend/schemas/profile.py と対応。 */
export type UserProfileInput = {
  name: string;
  location?: string | null;
  languages?: string[];
  occupation?: string | null;
  skills?: string[];
  experience?: string[];
  interests?: string[];
  goals?: string[];
  about?: string | null;
};

export type UserProfile = Required<Omit<UserProfileInput, 'location' | 'occupation' | 'about'>> & {
  user_id: string;
  location: string | null;
  occupation: string | null;
  about: string | null;
};
