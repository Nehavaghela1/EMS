import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { LocationListPage } from '../pages/LocationListPage'
import * as apiModule from '../../identity/api'

describe('Sub-feature 1.6: LocationListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderLocationListPage() {
    return render(
      <MemoryRouter initialEntries={['/settings/locations']}>
        <LocationListPage />
      </MemoryRouter>
    )
  }

  it('renders loading state initially and then shows empty state if no locations', async () => {
    vi.spyOn(apiModule, 'listLocations').mockResolvedValueOnce([])
    renderLocationListPage()

    expect(screen.getByText(/loading locations/i)).toBeInTheDocument()
    expect(await screen.findByText(/no locations found/i)).toBeInTheDocument()
    expect(screen.getByText(/work locations/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /\+ add location/i })).toHaveAttribute(
      'href',
      '/settings/locations/new'
    )
  })

  it('renders list of locations with Head Office badge for primary location', async () => {
    vi.spyOn(apiModule, 'listLocations').mockResolvedValueOnce([
      {
        id: 'loc-1',
        name: 'Headquarters',
        code: 'HQ-01',
        address_line1: '123 Tech Park',
        city: 'Bengaluru',
        state: 'Karnataka',
        country: 'IN',
        is_primary: true,
        is_active: true,
      } as any,
      {
        id: 'loc-2',
        name: 'Regional Office',
        code: 'RO-02',
        address_line1: '456 Commercial Street',
        city: 'Mumbai',
        state: 'Maharashtra',
        country: 'IN',
        is_primary: false,
        is_active: true,
      } as any,
    ])

    renderLocationListPage()

    expect(await screen.findByText('Headquarters')).toBeInTheDocument()
    expect(screen.getByText('HQ-01')).toBeInTheDocument()
    expect(screen.getByText('Head Office')).toBeInTheDocument()

    expect(screen.getByText('Regional Office')).toBeInTheDocument()
    expect(screen.getByText('RO-02')).toBeInTheDocument()
  })
})
