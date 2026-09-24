/**
 * Commands API Service
 *
 * Source of Truth: API_contract.md (37.0, 38.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  CommandDetailData,
  CommandListItemData,
  CommandState,
  PaginatedResponse,
  TargetType,
} from '../types/api';

export interface ListCommandsParams {
  command_type?: string;
  state?: CommandState | string;
  target_type?: TargetType | string;
  target_id?: string;
  from?: string;
  to?: string;
  cursor?: string | null;
  limit?: number;
}

export class CommandsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 37.0 GET /api/v1/commands/{command_id} — Get details and execution state of a control command
   */
  async getCommand(
    commandId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<CommandDetailData>> {
    return this.client.get<CommandDetailData>(
      `/api/v1/commands/${encodeURIComponent(commandId)}`,
      options
    );
  }

  /**
   * 38.0 GET /api/v1/commands — List asynchronous control commands for audit/monitoring
   */
  async listCommands(
    params?: ListCommandsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<CommandListItemData>> {
    return this.client.getPaginated<CommandListItemData>('/api/v1/commands', {
      ...options,
      params: {
        command_type: params?.command_type,
        state: params?.state,
        target_type: params?.target_type,
        target_id: params?.target_id,
        from: params?.from,
        to: params?.to,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }
}

export const commandsService = new CommandsService();
