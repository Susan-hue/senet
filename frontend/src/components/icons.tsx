import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function svgProps({ size = 20, ...props }: IconProps): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

export function EyeIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M2.5 12S5.5 5.5 12 5.5 21.5 12 21.5 12 18.5 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function EyeOffIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c6.5 0 9.5 7 9.5 7a14.7 14.7 0 0 1-2.3 3.2" />
      <path d="M6.6 6.6A14.6 14.6 0 0 0 2.5 12S5.5 19 12 19a9.2 9.2 0 0 0 4.4-1.1" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="M3 3l18 18" />
    </svg>
  );
}

export function CheckCircleIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M22 11.1V12a10 10 0 1 1-5.9-9.1" />
      <path d="M22 4 12 14.1l-3-3" />
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M10.3 3.7 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  );
}

export function MailIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 6-10 7L2 6" />
    </svg>
  );
}

export function ArrowLeftIcon(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );
}
