import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, type AxiosResponse } from 'axios'
import { ActivatePage } from '../pages/ActivatePage'
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

describe('Sub-feature 1.3: ActivatePage', () => {
  let queryClient: QueryClient
  const mockEstablishSession = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      status: 'unauthenticated',
      user: null,
      login: vi.fn(),
      establishSession: mockEstablishSession,
      logout: vi.fn(),
      sessionExpired: false,
    })
  })

  function renderActivatePage(token = 'valid-token-123') {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/activate/${token}`]}>
          <Routes>
            <Route path="/activate/:token" element={<ActivatePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )
  }

  it('renders invitation invalid view when token is unknown or expired (404)', async () => {
    const errorObj = makeAxiosError(404, {
      code: 'not_found',
      message: 'Invitation not found or has expired.',
    })
    vi.spyOn(apiModule, 'previewActivation').mockRejectedValueOnce(errorObj)
    renderActivatePage('expired-token')

    expect(await screen.findByRole('heading', { name: /invitation no longer valid/i })).toBeInTheDocument()
    expect(screen.getByText(/invitation not found or has expired/i)).toBeInTheDocument()
  })

  it('renders activation form with preview data when token is valid', async () => {
    vi.spyOn(apiModule, 'previewActivation').mockResolvedValueOnce({
      first_name: 'John',
      last_name: 'Doe',
      email: 'john@acme.com',
      company_name: 'Acme Corp',
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    } as any)
    renderActivatePage()

    expect(await screen.findByRole('heading', { name: /welcome, john doe/i })).toBeInTheDocument()
    expect(screen.getByText(/acme corp/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/choose a username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/choose a password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /activate account/i })).toBeInTheDocument()
  })

  it('displays client-side validation error when password is too weak', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'previewActivation').mockResolvedValueOnce({
      first_name: 'Jane',
      last_name: null,
      email: 'jane@acme.com',
      company_name: 'Acme Corp',
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    } as any)
    renderActivatePage()

    expect(await screen.findByRole('heading', { name: /welcome, jane/i })).toBeInTheDocument()

    await user.type(screen.getByLabelText(/choose a username/i), 'janedoe')
    await user.type(screen.getByLabelText(/choose a password/i), 'short')
    await user.click(screen.getByRole('button', { name: /activate account/i }))

    expect(
      screen.getByText(/password must contain at least one digit/i)
    ).toBeInTheDocument()
  })

  it('submits activation, establishes session, and activates successfully', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'previewActivation').mockResolvedValueOnce({
      first_name: 'John',
      last_name: 'Smith',
      email: 'john@acme.com',
      company_name: 'Acme Corp',
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    } as any)
    vi.spyOn(apiModule, 'activateAccount').mockResolvedValueOnce({
      access_token: 'fake-jwt-token-123',
      token_type: 'bearer',
    } as any)
    mockEstablishSession.mockResolvedValueOnce(undefined)

    renderActivatePage('test-token')
    expect(await screen.findByRole('heading', { name: /welcome, john smith/i })).toBeInTheDocument()

    await user.type(screen.getByLabelText(/choose a username/i), 'johnsmith')
    await user.type(screen.getByLabelText(/choose a password/i), 'ValidPassword123!')
    await user.click(screen.getByRole('button', { name: /activate account/i }))

    await waitFor(() => {
      expect(apiModule.activateAccount).toHaveBeenCalledWith({
        token: 'test-token',
        username: 'johnsmith',
        password: 'ValidPassword123!',
      })
      expect(mockEstablishSession).toHaveBeenCalledWith('fake-jwt-token-123')
    })
  })
})
