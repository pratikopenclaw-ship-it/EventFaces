import type { SVGProps } from "react";

// Small outline glyphs for EmptyState. Plain inline SVG, matching the rest of the app's
// no-icon-library approach (see src/components/ui.tsx). 24x24, stroke = currentColor so
// each one inherits EmptyState's icon colour.

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function CalendarIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 9.5h17M8 3v4M16 3v4" />
    </svg>
  );
}

export function FlagIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6 20V4" />
      <path d="M6 4.5c1.5-1 3.5-1 5 0s3.5 1 5 0v8c-1.5 1-3.5 1-5 0s-3.5-1-5 0z" />
    </svg>
  );
}

export function UndoIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M8 7 4 11l4 4" />
      <path d="M4 11h10a6 6 0 1 1 0 9" />
    </svg>
  );
}

export function PeopleIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3 19c0-3 2.7-5 6-5s6 2 6 5" />
      <circle cx="17" cy="9.5" r="2.25" />
      <path d="M15.3 14.3c2.4.3 4.2 2 4.2 4.7" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M19.5 19.5 15.3 15.3" />
    </svg>
  );
}

export function EnvelopeIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="M4 7l8 6 8-6" />
    </svg>
  );
}

export function CameraIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 8.5a2 2 0 0 1 2-2h1.3l1-1.6a1.5 1.5 0 0 1 1.3-.7h4.8a1.5 1.5 0 0 1 1.3.7l1 1.6H18a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
      <circle cx="12" cy="12.3" r="3.3" />
    </svg>
  );
}

export function FaceSearchIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M8 9.5h.01M13 9.5h.01" />
      <path d="M8.3 13c.7.8 1.6 1.2 2.7 1.2s2-.4 2.7-1.2" />
      <path d="M19.5 19.5 15.3 15.3" />
    </svg>
  );
}
