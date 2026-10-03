import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { Project } from './types'

type Input = { id: string; revision: number; archived: boolean }

/**
 * Archives or restores a project. The PATCH needs the revision the caller saw; if another tab
 * changed the project in the meantime (409) we read it again and retry once with the fresh revision.
 */
export function useSetArchived() {
  const queryClient = useQueryClient()
  return useMutation<Project, Error, Input>({
    mutationFn: async ({ id, revision, archived }) => {
      try {
        return await api.updateProject(id, { expected_revision: revision, archived })
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error
        const fresh = await api.project(id)
        if (!!fresh.archived === archived) return fresh
        return api.updateProject(id, { expected_revision: fresh.revision, archived })
      }
    },
    onSuccess: (project) => {
      queryClient.setQueryData(['project', project.id], project)
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

/** Most recently updated first. */
export function byRecent<T extends { updated_at: string }>(items: T[]): T[] {
  const time = (value: string) => {
    const parsed = Date.parse(value)
    return Number.isNaN(parsed) ? 0 : parsed
  }
  return [...items].sort((a, b) => time(b.updated_at) - time(a.updated_at))
}
