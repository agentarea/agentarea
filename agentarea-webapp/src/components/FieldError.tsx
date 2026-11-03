/** A form field's validation message under its input; nothing when it has none. */
export default function FieldError({ message }: { message?: string }) {
  return message ? (
    <p className="form-error" role="alert">
      {message}
    </p>
  ) : null;
}
