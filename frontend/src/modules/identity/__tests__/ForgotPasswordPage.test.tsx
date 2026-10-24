import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AxiosError, type AxiosResponse } from 'axios'
import { ForgotPasswordPage } from '../pages/ForgotPasswordPage'
import * as apiModule from '../api'

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

describe('Sub-feature 1.4: ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderForgotPasswordPage() {
    return render(
      <MemoryRouter initialEntries={['/forgot-password']}>
        <Routes>
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/login" element={<div>Login Page Target</div>} />
        </Routes>
      </MemoryRouter>
    )
  }

  it('renders request step with email input and submit button', () => {
    renderForgotPasswordPage()
    expect(screen.getByRole('heading', { name: /forgot password/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send reset code/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to sign in/i })).toHaveAttribute(
      'href',
      '/login'
    )
  })

  it('transitions to reset code step when request succeeds', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'forgotPassword').mockResolvedValueOnce({
      message: 'If an account exists, a reset code was sent.',
    } as any)
    renderForgotPasswordPage()

    await user.type(screen.getByLabelText(/email/i), 'user@example.com')
    await user.click(screen.getByRole('button', { name: /send reset code/i }))

    expect(await screen.findByRole('heading', { name: /enter your reset code/i })).toBeInTheDocument()
    expect(screen.getByText('If an account exists, a reset code was sent.')).toBeInTheDocument()
    expect(screen.getByLabelText(/reset code/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/new password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reset password/i })).toBeInTheDocument()
  })

  it('submits reset with valid code and password and navigates to login', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'forgotPassword').mockResolvedValueOnce({
      message: 'If an account exists, a reset code was sent.',
    } as any)
    vi.spyOn(apiModule, 'resetPassword').mockResolvedValueOnce({
      message: 'Password reset successfully.',
    } as any)
    renderForgotPasswordPage()

    // Step 1
    await user.type(screen.getByLabelText(/email/i), 'user@example.com')
    await user.click(screen.getByRole('button', { name: /send reset code/i }))

    expect(await screen.findByRole('heading', { name: /enter your reset code/i })).toBeInTheDocument()

    // Step 2
    await user.type(screen.getByLabelText(/reset code/i), '123456')
    await user.type(screen.getByLabelText(/new password/i), 'NewPassword123!')
    await user.click(screen.getByRole('button', { name: /reset password/i }))

    await waitFor(() => {
      expect(apiModule.resetPassword).toHaveBeenCalledWith({
        email: 'user@example.com',
        otp: '123456',
        new_password: 'NewPassword123!',
      })
      expect(screen.getByText('Login Page Target')).toBeInTheDocument()
    })
  })

  it('displays error when reset code is invalid or expired (400/404)', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'forgotPassword').mockResolvedValueOnce({
      message: 'If an account exists, a reset code was sent.',
    } as any)
    const errorObj = makeAxiosError(400, {
      code: 'invalid_code',
      message: 'Invalid or expired code.',
    })
    vi.spyOn(apiModule, 'resetPassword').mockRejectedValueOnce(errorObj)
    renderForgotPasswordPage()

    await user.type(screen.getByLabelText(/email/i), 'user@example.com')
    await user.click(screen.getByRole('button', { name: /send reset code/i }))

    expect(await screen.findByRole('heading', { name: /enter your reset code/i })).toBeInTheDocument()

    await user.type(screen.getByLabelText(/reset code/i), '999999')
    await user.type(screen.getByLabelText(/new password/i), 'NewPassword123!')
    await user.click(screen.getByRole('button', { name: /reset password/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid or expired code.')).toBeInTheDocument()
    })
  })
})
