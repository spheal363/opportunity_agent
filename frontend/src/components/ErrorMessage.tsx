export default function ErrorMessage({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      {error}
    </p>
  );
}
