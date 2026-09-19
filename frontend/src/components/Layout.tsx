import { NavLink, Outlet } from 'react-router-dom';

import { USE_MOCK } from '../api';

const LINKS = [
  { to: '/profile', label: 'Profile' },
  { to: '/opportunities', label: 'Opportunities' },
];

export default function Layout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center gap-6 px-6 py-4">
          <span className="font-semibold">Opportunity Agent</span>
          <nav className="flex gap-4 text-sm">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  isActive ? 'text-slate-900 underline' : 'text-slate-500 hover:text-slate-900'
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          {USE_MOCK && (
            <span className="ml-auto rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
              MOCK
            </span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
