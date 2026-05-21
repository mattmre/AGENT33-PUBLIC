/**
 * VisuallyHidden: A utility component for screen-reader-only text.
 *
 * The content is clipped from visual rendering but remains accessible
 * to screen readers and other assistive technologies.
 *
 * Uses the "sr-only" CSS class which applies the standard visually-hidden
 * pattern (clip, 1px dimensions, overflow hidden, absolute positioning).
 */
export function VisuallyHidden({ children }: { children: React.ReactNode }): JSX.Element {
  return <span className="sr-only">{children}</span>;
}
