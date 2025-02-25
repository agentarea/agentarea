import { SourceType, SourceStatus } from '@/types/source';

export interface SourceBase {
  name: string;
  type: SourceType;
  description: string;
  configuration: Record<string, any>;
  metadata: Record<string, any>;
  owner: string;
  source_spec_id?: string;
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

export interface ConfigField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  description?: string;
  default?: any;
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
  validation?: Record<string, any>;
}

export interface SourceSpecification {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  type: SourceType;
  config_fields: ConfigField[];
  capabilities: string[];
  documentation_url?: string;
  auth_type?: string;
}

export interface SourceSpecificationResponse {
  specifications: SourceSpecification[];
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const PUBLIC_S3_ENDPOINT = process.env.NEXT_PUBLIC_S3_ENDPOINT || 'http://localhost:9000';

// Function to fix presigned URLs that might contain internal endpoints
const fixPresignedUrl = (url: string): string => {
  // Check if the URL contains internal references like minio:9000
  if (url.includes('minio:9000')) {
    return url.replace('minio:9000', PUBLIC_S3_ENDPOINT.replace(/^https?:\/\//, ''));
  }
  
  // Add more replacements as needed for other internal endpoints
  
  return url;
};

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

  async listSourceSpecifications(category?: string): Promise<SourceSpecification[]> {
    const url = new URL(`${API_BASE_URL}/source-specifications/`);
    if (category) {
      url.searchParams.append('category', category);
    }

    const response = await fetch(url.toString());

    if (!response.ok) {
      throw new Error('Failed to fetch source specifications');
    }

    const data = await response.json();
    return data.specifications;
  },

  async getSourceSpecification(specId: string): Promise<SourceSpecification> {
    const response = await fetch(`${API_BASE_URL}/source-specifications/${specId}`);

    if (!response.ok) {
      throw new Error('Failed to fetch source specification');
    }

    return response.json();
  },

  async testConnection(configuration: Record<string, any>, sourceSpecId: string): Promise<{ success: boolean; message: string }> {
    // This would be a real API call in production
    // For now, we'll simulate a successful connection after a delay
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({ success: true, message: 'Connection successful' });
      }, 1500);
    });
  },

  async uploadFiles(files: File[], options?: { 
    processingType?: string; 
    saveAsTemplate?: boolean;
    templateName?: string;
  }): Promise<{ success: boolean; message: string; sourceId?: string }> {
    try {
      // Process each file with presigned URLs
      const results = await Promise.all(
        files.map(async (file) => {
          // Step 1: Get a presigned URL for the file
          const presignedResponse = await fetch(`${API_BASE_URL}/sources/presigned-url/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              filename: file.name,
              file_type: file.name.split('.').pop() || 'unknown',
              content_type: file.type,
            }),
          });
          
          if (!presignedResponse.ok) {
            const errorData = await presignedResponse.json().catch(() => ({}));
            throw new Error(errorData.message || 'Failed to get presigned URL');
          }
          
          const presignedData = await presignedResponse.json();
          
          // Fix the presigned URL if it contains internal endpoints
          const fixedPresignedUrl = fixPresignedUrl(presignedData.presigned_url);
          
          // Step 2: Upload the file directly to S3 using the presigned URL
          const uploadResponse = await fetch(fixedPresignedUrl, {
            method: 'PUT',
            headers: {
              'Content-Type': file.type,
            },
            body: file,
          });
          
          if (!uploadResponse.ok) {
            throw new Error('Failed to upload file to S3');
          }
          
          // Step 3: Create the source record after successful upload
          const sourceResponse = await fetch(`${API_BASE_URL}/sources/after-upload/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              source_id: presignedData.source_id,
              s3_key: presignedData.s3_key,
              filename: file.name,
              file_type: file.name.split('.').pop() || 'unknown',
              content_type: file.type,
              file_size: file.size,
              description: options?.processingType ? `File processed with ${options.processingType}` : undefined,
              owner: 'user', // Default owner
            }),
          });
          
          if (!sourceResponse.ok) {
            const errorData = await sourceResponse.json().catch(() => ({}));
            throw new Error(errorData.message || 'Failed to create source record');
          }
          
          return await sourceResponse.json();
        })
      );
      
      // Return success with the ID of the first source (for backward compatibility)
      return {
        success: true,
        message: 'Files uploaded successfully',
        sourceId: results[0]?.source_id
      };
    } catch (error) {
      console.error('File upload error:', error);
      return {
        success: false,
        message: error instanceof Error ? error.message : 'Failed to upload files'
      };
    }
  }
}; 