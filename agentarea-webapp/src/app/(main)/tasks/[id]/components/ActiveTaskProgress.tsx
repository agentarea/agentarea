import { FileText, Loader2 } from "lucide-react";

interface TaskStatus {
  status: string;
  message?: string;
  artifacts?: unknown[];
}

interface ActiveTaskProgressProps {
  isActive: boolean;
  currentStatus: string;
  taskStatus: TaskStatus | null;
}

export default function ActiveTaskProgress({
  isActive,
  currentStatus,
  taskStatus,
}: ActiveTaskProgressProps) {
  if (!isActive) {
    return null;
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-gradient-to-r from-blue-50 to-sky-50 p-3 dark:border-blue-800 dark:from-blue-900/20 dark:to-sky-900/20">
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/40">
            <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {currentStatus === "running"
                ? "Running..."
                : currentStatus === "paused"
                  ? "Paused"
                  : currentStatus}
            </h3>
            <span className="text-xs text-gray-600 dark:text-gray-400">
              {taskStatus?.message || "In progress"}
            </span>
          </div>

          <div className="mb-2">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white dark:bg-gray-800">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  currentStatus === "running"
                    ? "animate-pulse bg-gradient-to-r from-blue-500 to-blue-600"
                    : currentStatus === "paused"
                      ? "bg-gradient-to-r from-yellow-400 to-yellow-500"
                      : "bg-gradient-to-r from-red-400 to-red-500"
                }`}
                style={{
                  width: currentStatus === "running" ? "65%" : "35%",
                }}
              />
            </div>
          </div>

          {taskStatus?.artifacts && taskStatus.artifacts.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <span className="mr-1 text-xs text-gray-700 dark:text-gray-300">
                Generated:
              </span>
              {taskStatus.artifacts.slice(0, 2).map((artifact, index) => (
                <div
                  key={index}
                  className="flex items-center gap-1 rounded bg-white px-2 py-0.5 text-xs dark:bg-gray-800"
                >
                  <FileText className="h-2.5 w-2.5 text-blue-600" />
                  <span>
                    {typeof artifact === "string"
                      ? artifact
                      : `Artifact ${index + 1}`}
                  </span>
                </div>
              ))}
              {taskStatus.artifacts.length > 2 && (
                <span className="text-xs text-gray-500">
                  +{taskStatus.artifacts.length - 2} more
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
