import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AxiosError, type AxiosResponse } from 'axios'
import { LoginPage } from '../pages/LoginPage'
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

describe('Sub-feature 1.1: LoginPage', () => {
  const mockLogin = vi.fn()
  const defaultAuthValue: AuthContextModule.AuthContextValue = {
    status: 'unauthenticated',
    user: null,
    login: mockLogin,
    establishSession: vi.fn(),
    logout: vi.fn(),
    sessionExpired: false,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue(defaultAuthValue)
  })

  function renderLoginPage(initialEntries = ['/login'], authOverrides = {}) {
    if (Object.keys(authOverrides).length > 0) {
      vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
        ...defaultAuthValue,
        ...authOverrides,
      })
    }
    return render(
      <MemoryRouter initialEntries={initialEntries}>
        <LoginPage />
      </MemoryRouter>
    )
  }

  it('renders login form with email, password fields and sign in button', () => {
    renderLoginPage()
    expect(screen.getByRole('heading', { name: /ems/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /forgot password/i })).toHaveAttribute(
      'href',
      '/forgot-password'
    )
    expect(
      screen.getByRole('link', { name: /register your company/i })
    ).toHaveAttribute('href', '/register-company')
  })

  it('submits form with entered email and password to login()', async () => {
    const user = userEvent.setup()
    mockLogin.mockResolvedValueOnce(undefined)
    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'alice@example.com')
    await user.type(screen.getByLabelText('Password'), 'Password123!')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(mockLogin).toHaveBeenCalledWith('alice@example.com', 'Password123!', undefined)
  })

  it('renders error alert when login fails (e.g. invalid credentials 401)', async () => {
    const user = userEvent.setup()
    const errorObj = makeAxiosError(401, {
      code: 'invalid_credentials',
      message: 'Invalid email or password.',
    })
    mockLogin.mockRejectedValueOnce(errorObj)
    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'wrong@example.com')
    await user.type(screen.getByLabelText('Password'), 'BadPass123!')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid email or password.')).toBeInTheDocument()
    })
  })

  it('displays human-readable lock message when account is locked out', async () => {
    const user = userEvent.setup()
    const lockTime = new Date(Date.now() + 15 * 60 * 1000).toISOString()
    const errorObj = makeAxiosError(423, {
      code: 'account_locked',
      message: 'Account locked.',
      details: { locked_until: lockTime },
    })
    mockLogin.mockRejectedValueOnce(errorObj)
    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'locked@example.com')
    await user.type(screen.getByLabelText('Password'), 'Pass1234!')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/too many failed attempts\. try again after/i)
      ).toBeInTheDocument()
    })
  })

  it('reveals company code input when company_required error is returned', async () => {
    const user = userEvent.setup()
    const errorObj = makeAxiosError(400, {
      code: 'company_required',
      message: 'Multiple workspaces found. Specify your company code.',
      details: { companies: ['CORP-A', 'CORP-B'] },
    })
    mockLogin.mockRejectedValueOnce(errorObj)
    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'multi@example.com')
    await user.type(screen.getByLabelText('Password'), 'Pass1234!')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/multiple workspaces found\. specify your company code\./i)
      ).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/select or enter the company code/i)).toBeInTheDocument()
    expect(screen.getByText(/CORP-A/i)).toBeInTheDocument()
    expect(screen.getByText(/CORP-B/i)).toBeInTheDocument()
  })

  it('displays session expired alert if redirected due to expired session', () => {
    renderLoginPage(['/login'], { sessionExpired: true })
    expect(
      screen.getByText('Your session expired. Sign in again to continue.')
    ).toBeInTheDocument()
  })
})
