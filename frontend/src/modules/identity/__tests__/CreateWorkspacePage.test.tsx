import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AxiosError, type AxiosResponse } from 'axios'
import { CreateWorkspacePage } from '../pages/CreateWorkspacePage'
import * as apiModule from '../api'
import * as AuthContextModule from '../../../app/auth-context'

function makeAxiosError(
  status: number,
  errorData: { code: string; message: string; details?: Record<string, unknown> }
) {
  const response = {
    status,
    data: {
      error: {
        code: errorData.code,
        message: errorData.message,
        details: errorData.details ?? null,
        request_id: 'test-req-id',
      },
    },
  } as AxiosResponse
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, response)
}

describe('Sub-feature 1.5: CreateWorkspacePage', () => {
  const mockEstablishSession = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      status: 'authenticated',
      user: {
        id: 'user-1',
        email: 'owner@acme.com',
        role: 'owner',
        company_id: 'comp-1',
        is_active: true,
        must_change_password: false,
        employee: null,
        permissions: [],
      },
      login: vi.fn(),
      establishSession: mockEstablishSession,
      logout: vi.fn(),
      sessionExpired: false,
    })
  })

  function renderCreateWorkspacePage() {
    return render(
      <MemoryRouter initialEntries={['/create-workspace']}>
        <CreateWorkspacePage />
      </MemoryRouter>
    )
  }

  it('renders Step 1 with company name, country, and subdomain inputs', () => {
    renderCreateWorkspacePage()
    expect(screen.getByRole('heading', { name: /create new workspace/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /legal entity details/i })).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/infiria tech pvt ltd/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /next step →/i })).toBeInTheDocument()
  })

  it('advances through Step 1 to Step 2 and Step 3', async () => {
    const user = userEvent.setup()
    renderCreateWorkspacePage()

    // Step 1
    await user.type(screen.getByPlaceholderText(/infiria tech pvt ltd/i), 'New Corp')
    await user.click(screen.getByRole('button', { name: /next step →/i }))

    // Step 2
    expect(await screen.findByRole('heading', { name: /regional settings/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /next step →/i }))

    // Step 3
    expect(await screen.findByRole('heading', { name: /starter defaults/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /launch workspace/i })).toBeInTheDocument()
  })

  it('submits form at Step 3 and calls createWorkspace with form data', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'createWorkspace').mockResolvedValueOnce({
      company: {
        id: 'new-comp-id',
        name: 'New Corp',
        code: 'NC-001',
      },
      access_token: 'new-workspace-jwt',
      token_type: 'bearer',
    } as any)
    mockEstablishSession.mockResolvedValueOnce(undefined)

    renderCreateWorkspacePage()

    // Step 1
    await user.type(screen.getByPlaceholderText(/infiria tech pvt ltd/i), 'New Corp')
    await user.click(screen.getByRole('button', { name: /next step →/i }))

    // Step 2
    expect(await screen.findByRole('heading', { name: /regional settings/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /next step →/i }))

    // Step 3
    expect(await screen.findByRole('heading', { name: /starter defaults/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /launch workspace/i }))

    await waitFor(() => {
      expect(apiModule.createWorkspace).toHaveBeenCalledWith(
        expect.objectContaining({
          company_name: 'New Corp',
          currency: 'INR',
          seed_departments: true,
          seed_shift: true,
        })
      )
      expect(mockEstablishSession).toHaveBeenCalledWith('new-workspace-jwt')
    })
  })
})
