/**
 * ① 初回プロフィール入力。
 * 土台としての最小フォーム。実際の入力 UX は後続タスクで作り込む。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { saveProfile, startAgentRun } from '../api';
import ErrorMessage from '../components/ErrorMessage';
import { parseList } from '../utils/date';

const FIELDS = [
  { key: 'name', label: '名前', list: false },
  { key: 'location', label: '活動地域', list: false },
  { key: 'occupation', label: '職業・現在の立場', list: false },
  { key: 'skills', label: 'スキル（カンマ区切り）', list: true },
  { key: 'interests', label: '興味・趣味（カンマ区切り）', list: true },
  { key: 'goals', label: '目標・やりたいこと（カンマ区切り）', list: true },
] as const;

export default function ProfilePage() {
  const navigate = useNavigate();
  const [values, setValues] = useState<Record<string, string>>({
    name: 'Naoya',
    location: 'Tokyo, Japan',
    occupation: 'Backend Engineer',
    skills: 'Java, Python, AWS, AI Agent',
    interests: 'AI, Startup, Entrepreneurship, Music, DJ',
    goals: 'Build AI products, Start a company, Work internationally',
    about: 'AI Agentや起業、音楽に興味があります。',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (key: string, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await saveProfile({
        name: values.name,
        location: values.location,
        occupation: values.occupation,
        skills: parseList(values.skills),
        interests: parseList(values.interests),
        goals: parseList(values.goals),
        about: values.about,
      });
      const run = await startAgentRun();
      navigate(`/explore?run_id=${run.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存に失敗しました');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">プロフィール</h1>
        <p className="mt-1 text-sm text-slate-600">
          検索キーワードは入力しません。Agent が目標から「何を探すか」を決めます。
        </p>
      </div>

      {FIELDS.map((field) => (
        <label key={field.key} className="block">
          <span className="text-sm text-slate-700">{field.label}</span>
          <input
            value={values[field.key] ?? ''}
            onChange={(e) => update(field.key, e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          />
        </label>
      ))}

      <label className="block">
        <span className="text-sm text-slate-700">自己紹介（任意）</span>
        <textarea
          value={values.about ?? ''}
          onChange={(e) => update('about', e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
        />
      </label>

      <ErrorMessage error={error} />

      <button
        type="submit"
        disabled={submitting || !values.name}
        className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
      >
        {submitting ? '開始しています…' : 'Agent に探索してもらう'}
      </button>
    </form>
  );
}
