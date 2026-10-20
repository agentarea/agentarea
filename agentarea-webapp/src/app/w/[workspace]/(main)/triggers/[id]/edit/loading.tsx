import TriggerFormSkeleton from "../../create/TriggerFormSkeleton";

// Without its own boundary /edit fell back to the overview's skeleton, so the
// overview flashed up before the form.
export default function Loading() {
  return <TriggerFormSkeleton />;
}
