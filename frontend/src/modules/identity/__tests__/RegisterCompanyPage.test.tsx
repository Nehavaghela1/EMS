import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, type AxiosResponse } from 'axios'
import { RegisterCompanyPage } from '../pages/RegisterCompanyPage'
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

describe('Sub-feature 1.2: RegisterCompanyPage', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    vi.clearAllMocks()
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.spyOn(apiModule, 'listIndustryPresets').mockResolvedValue([])
  })

  function renderRegisterPage() {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/register-company']}>
          <RegisterCompanyPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
  }

  it('renders registration form with all required inputs', () => {
    renderRegisterPage()
    expect(screen.getByRole('heading', { name: /register your company/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/company name \*/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/admin \/ company work email \*/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/workspace url/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^password \*/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/confirm password \*/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /register company/i })).toBeInTheDocument()
  })

  it('auto-suggests clean subdomain when typing company name', async () => {
    const user = userEvent.setup()
    renderRegisterPage()

    await user.type(screen.getByLabelText(/company name \*/i), 'Acme Corp')
    expect(screen.getByLabelText(/workspace url/i)).toHaveValue('acmecorp')
  })

  it('displays validation error if password confirmation does not match', async () => {
    const user = userEvent.setup()
    renderRegisterPage()

    await user.type(screen.getByLabelText(/company name \*/i), 'Acme Corp')
    await user.type(screen.getByLabelText(/admin \/ company work email \*/i), 'admin@acme.com')
    await user.selectOptions(screen.getByLabelText(/company size/i), '1-10')
    await user.type(screen.getByLabelText(/^password \*/i), 'SecurePass123!')
    await user.type(screen.getByLabelText(/confirm password \*/i), 'DifferentPass123!')
    await user.click(screen.getByRole('button', { name: /register company/i }))

    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument()
  })

  it('displays 422 error when server rejects reserved subdomain', async () => {
    const user = userEvent.setup()
    const errorObj = makeAxiosError(422, {
      code: 'validation_error',
      message: 'This subdomain is reserved.',
      details: { errors: [{ loc: ['body', 'subdomain'], msg: 'This subdomain is reserved.' }] },
    })
    vi.spyOn(apiModule, 'registerCompany').mockRejectedValueOnce(errorObj)
    renderRegisterPage()

    await user.type(screen.getByLabelText(/company name \*/i), 'Admin Corp')
    const subInput = screen.getByLabelText(/workspace url/i)
    await user.clear(subInput)
    await user.type(subInput, 'admin')
    await user.type(screen.getByLabelText(/admin \/ company work email \*/i), 'owner@admin.com')
    await user.selectOptions(screen.getByLabelText(/company size/i), '1-10')
    await user.type(screen.getByLabelText(/^password \*/i), 'SecurePass123!')
    await user.type(screen.getByLabelText(/confirm password \*/i), 'SecurePass123!')
    await user.click(screen.getByRole('button', { name: /register company/i }))

    await waitFor(() => {
      const msgs = screen.getAllByText('This subdomain is reserved.')
      expect(msgs.length).toBeGreaterThan(0)
    })
  })

  it('renders success confirmation view upon successful registration', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'registerCompany').mockResolvedValueOnce({
      id: 'comp-123',
      name: 'Acme Global',
      code: 'AG-1001',
      subdomain: 'acmeglobal',
      status: 'pending',
      created_at: new Date().toISOString(),
    } as any)
    renderRegisterPage()

    await user.type(screen.getByLabelText(/company name \*/i), 'Acme Global')
    await user.type(screen.getByLabelText(/admin \/ company work email \*/i), 'admin@acmeglobal.com')
    await user.selectOptions(screen.getByLabelText(/company size/i), '1-10')
    await user.type(screen.getByLabelText(/^password \*/i), 'SecurePass123!')
    await user.type(screen.getByLabelText(/confirm password \*/i), 'SecurePass123!')
    await user.click(screen.getByRole('button', { name: /register company/i }))

    await waitFor(() => {
      expect(screen.getByText(/workspace registered!/i)).toBeInTheDocument()
      expect(screen.getByText('AG-1001')).toBeInTheDocument()
      expect(screen.getByText(/https:\/\/acmeglobal\.ems-pro\.com/i)).toBeInTheDocument()
    })
  })
})
