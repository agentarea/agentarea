import Link from 'next/link';
import { Source } from '@/types/source';

interface Props {
  source: Source;
}

export function SourceCard({ source }: Props) {
  return (
    <Link href={`/sources/${source.source_id}`}>
      <div className="border rounded-lg p-4 hover:shadow-lg transition-shadow">
        <div className="flex justify-between items-start">
          <h2 className="text-xl font-semibold">{source.name}</h2>
          <span className={`px-2 py-1 rounded text-sm ${getStatusColor(source.status)}`}>
            {source.status}
          </span>
        </div>
        <p className="text-gray-600 mt-2">{source.description}</p>
        <div className="mt-4 flex justify-between items-center">
          <span className="text-sm text-gray-500">{source.type}</span>
          <span className="text-sm text-gray-500">
            {new Date(source.updated_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </Link>
  );
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'active':
      return 'bg-green-100 text-green-800';
    case 'inactive':
      return 'bg-yellow-100 text-yellow-800';
    case 'error':
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
} 