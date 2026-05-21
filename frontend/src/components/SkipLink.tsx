/**
 * SkipLink: A skip-to-main-content link for keyboard users.
 *
 * Renders an anchor that is visually hidden until focused via Tab,
 * allowing keyboard users to bypass repeated navigation elements.
 *
 * The target element must have id="main-content".
 */
export function SkipLink(): JSX.Element {
  return (
    <a href="#main-content" className="skip-link">
      Skip to main content
    </a>
  );
}
