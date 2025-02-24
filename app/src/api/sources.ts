import { SourceType, SourceStatus } from '@/types/source';

export interface SourceBase {
  name: string;
  type: SourceType;
  description: string;
  configuration: Record<string, any>;
  metadata: Record<string, any>;
  owner: string;
}

export interface SourceCreate extends SourceBase {}

export interface SourceUpdate {
  name?: string;
  description?: string;
  configuration?: Record<string, any>;
  metadata?: Record<string, any>;
  status?: SourceStatus;
}

export interface SourceResponse extends SourceBase {
  source_id: string;
  created_at: string;
  updated_at: string;
  status: SourceStatus;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const sourcesApi = {
  async createSource(source: SourceCreate): Promise<SourceResponse> {
    const response = await fetch(`${API_BASE_URL}/sources/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(source),
    });

    if (!response.ok) {
      throw new Error('Failed to create source');
    }

    return response.json();
  },

  async listSources(): Promise<SourceResponse[]> {
    const response = await fetch(`${API_BASE_URL}/sources/`);

    if (!response.ok) {
      throw new Error('Failed to fetch sources');
    }

    return response.json();
  },

  async getSource(sourceId: string): Promise<SourceResponse> {
    const response = await fetch(`${API_BASE_URL}/sources/${sourceId}`);

    if (!response.ok) {
      throw new Error('Failed to fetch source');
    }

    return response.json();
  },

  async updateSource(sourceId: string, update: SourceUpdate): Promise<SourceResponse> {
    const response = await fetch(`${API_BASE_URL}/sources/${sourceId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(update),
    });

    if (!response.ok) {
      throw new Error('Failed to update source');
    }

    return response.json();
  },

  async deleteSource(sourceId: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/sources/${sourceId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new Error('Failed to delete source');
    }
  },
}; 