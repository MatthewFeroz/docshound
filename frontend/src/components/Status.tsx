export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="page-status">{label}</div>;
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="run-error page-error" role="alert">
      <span className="hero-eyebrow">Unable to continue</span>
      <h2>Something went wrong</h2>
      <p>{message}</p>
    </div>
  );
}
