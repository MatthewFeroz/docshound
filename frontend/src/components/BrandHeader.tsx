import { Link } from "react-router-dom";

interface BrandHeaderProps {
  suffix?: string;
  tagline: string;
  children?: React.ReactNode;
}

export function BrandHeader({ suffix, tagline, children }: BrandHeaderProps) {
  return (
    <header className="topbar">
      <Link className="brand" to="/" aria-label="DocsHound home">
        <img className="logo" src="/logos/docshound.png" alt="" />
        <div>
          <h1>
            <span className="brand-docs">Docs</span>
            <span className="brand-hound">Hound</span>
            {suffix ? ` ${suffix}` : ""}
          </h1>
          <p>{tagline}</p>
        </div>
      </Link>
      {children}
    </header>
  );
}
