import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsPage } from '../pages/SettingsPage'
import * as apiModule from '../api'
import * as hrApiModule from '../../hr/api'
import * as AuthContextModule from '../../../app/auth-context'
import * as ToastContextModule from '../../../app/toast-context'

describe('Sub-feature 1.7: Roles & Access Control in SettingsPage', () => {
  let queryClient: QueryClient
  const mockNotify = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.spyOn(ToastContextModule, 'useToast').mockReturnValue({
      notify: mockNotify,
    })
    vi.spyOn(hrApiModule, 'getMyEmployee').mockResolvedValue({
      id: 'emp-1',
      first_name: 'Owner',
      last_name: 'User',
      email: 'owner@acme.com',
      employee_code: 'EMP-001',
      employment_type: 'full_time',
      hire_date: '2025-01-01',
    } as any)
    vi.spyOn(hrApiModule, 'listDepartments').mockResolvedValue({ items: [], total: 0 } as any)
    vi.spyOn(apiModule, 'getMyCompany').mockResolvedValue({
      id: 'comp-1',
      name: 'Acme Corp',
      code: 'ACME-01',
      country: 'IN',
    } as any)
  })

  function renderSettingsPage(role: AuthContextModule.UserRole = 'owner') {
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      status: 'authenticated',
      user: {
        id: 'user-owner',
        email: 'owner@acme.com',
        role,
        company_id: 'comp-1',
        is_active: true,
        must_change_password: false,
        employee: {
          id: 'emp-1',
          employee_code: 'EMP-001',
          first_name: 'Owner',
          last_name: 'User',
          department_id: null,
          position: 'CEO',
        },
        permissions: [],
      },
      login: vi.fn(),
      establishSession: vi.fn(),
      logout: vi.fn(),
      sessionExpired: false,
    })

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/settings']}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
  }

  it('renders Administrators & Access Control section when user is owner', async () => {
    vi.spyOn(apiModule, 'listAdministrators').mockResolvedValueOnce([
      {
        id: 'user-owner',
        email: 'owner@acme.com',
        first_name: 'Owner',
        last_name: 'User',
        role: 'owner',
      } as any,
      {
        id: 'user-hr',
        email: 'hr@acme.com',
        first_name: 'HR',
        last_name: 'Admin',
        role: 'hr_admin',
      } as any,
    ])

    renderSettingsPage('owner')

    expect(
      await screen.findByRole('heading', { name: /administrators & access control/i })
    ).toBeInTheDocument()
    expect(await screen.findByText('👑 Primary Owner')).toBeInTheDocument()
    expect(screen.getByText('🛡️ HR Admin')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /assign hr admin/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /revoke admin access/i })).toBeInTheDocument()
  })

  it('does NOT render Administrators section if user is plain employee', () => {
    renderSettingsPage('employee')
    expect(
      screen.queryByRole('heading', { name: /administrators & access control/i })
    ).not.toBeInTheDocument()
  })

  it('revoking admin access calls updateUserRole with employee role', async () => {
    const user = userEvent.setup()
    vi.spyOn(apiModule, 'listAdministrators').mockResolvedValueOnce([
      {
        id: 'user-hr',
        email: 'hr@acme.com',
        first_name: 'HR',
        last_name: 'Admin',
        role: 'hr_admin',
      } as any,
    ])
    vi.spyOn(apiModule, 'updateUserRole').mockResolvedValueOnce({
      id: 'user-hr',
      role: 'employee',
      previous_role: 'hr_admin',
      changed: true,
    } as any)

    renderSettingsPage('owner')

    const revokeBtn = await screen.findByRole('button', { name: /revoke admin access/i })
    await user.click(revokeBtn)

    // Confirm modal
    const confirmBtn = await screen.findByRole('button', { name: /yes, revoke access/i })
    await user.click(confirmBtn)

    await waitFor(() => {
      expect(apiModule.updateUserRole).toHaveBeenCalledWith('user-hr', 'employee')
      expect(mockNotify).toHaveBeenCalledWith(
        expect.stringContaining('admin access revoked'),
        'success'
      )
    })
  })
})
