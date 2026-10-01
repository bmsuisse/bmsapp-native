// The same payloads as in contract-fixtures/ (see the README there), here as
// typed objects: the compiler checks them against the TS types, the test
// checks that they match the JSON files the Python side validates as well.

import { describe, expect, it } from 'vitest'
import type { LiveActivityState, Widget } from '../src/index.js'
import widgetsJson from '../../../contract-fixtures/widgets.json'
import liveActivityStateJson from '../../../contract-fixtures/live-activity-state.json'

const widgets: Widget[] = [
  {
    id: 'open-orders',
    kind: 'kpi',
    title: 'Open orders',
    icon: 'shippingbox',
    tint: '#2e4a62',
    path: '/orders',
    updatedAt: '2026-09-29T08:00:00Z',
    data: {
      value: 12,
      unit: 'pcs',
      caption: 'since Monday',
      trend: { direction: 'up', text: '+3', positive: false },
    },
  },
  {
    id: 'week',
    kind: 'stats',
    size: 'medium',
    title: 'This week',
    data: {
      items: [
        { label: 'Visits', value: 14 },
        { label: 'Umsatz', value: "CHF 12'400", trend: { direction: 'flat' } },
      ],
    },
  },
  {
    id: 'approvals',
    kind: 'list',
    title: 'To approve',
    data: {
      maxVisible: 3,
      emptyText: 'Nothing open',
      items: [
        {
          id: 'A-1001',
          title: 'Vacation request',
          subtitle: 'M. Muster',
          trailing: '3 days',
          path: '/approvals/A-1001',
          actions: [
            { id: 'approve', label: 'Approve', biometric: true },
            {
              id: 'reject',
              label: 'Reject',
              style: 'destructive',
              confirm: 'Really reject?',
            },
          ],
        },
      ],
    },
  },
  {
    id: 'revenue',
    kind: 'chart',
    data: {
      type: 'line',
      unit: 'CHF',
      series: [
        {
          name: '2026',
          color: '#e60014',
          points: [
            { x: 'Jan', y: 10.5 },
            { x: 'Feb', y: 12 },
          ],
        },
      ],
    },
  },
  {
    id: 'target',
    kind: 'progress',
    data: { value: 0.6, total: 1, caption: '60 % vom Ziel', style: 'ring' },
  },
  {
    id: 'hint',
    kind: 'text',
    defaultEnabled: false,
    data: { markdown: '**New:** Scan directly from the app', linkLabel: 'More' },
  },
  {
    id: 'new-visit',
    kind: 'action',
    required: true,
    data: {
      text: 'Record visit',
      pages: [
        {
          title: 'Customer',
          fields: [
            {
              id: 'customer',
              type: 'search',
              label: 'Customer',
              minQueryLength: 0,
              required: true,
            },
            { id: 'express', type: 'toggle', label: 'Express', value: false },
          ],
        },
        {
          fields: [
            { id: 'reason', label: 'Reason', visibleIf: { field: 'express', equals: true } },
            {
              id: 'article',
              type: 'select',
              options: [{ value: 'A1', label: 'Item 1' }, { value: 'A2' }],
            },
            { id: 'contact', type: 'select', remote: true, value: 'c-1', valueLabel: 'Anna' },
          ],
        },
      ],
      buttons: [{ id: 'save', label: 'Speichern', icon: 'checkmark' }],
    },
  },
  {
    id: 'news',
    kind: 'news',
    size: 'tall',
    data: {
      emptyText: 'No news',
      items: [
        {
          id: 'n-1',
          title: 'New location',
          text: 'From October in Bern.',
          imageUrl: '/img/bern.jpg',
          path: '/news/n-1',
          date: '2026-09-28T10:00:00Z',
          caption: 'HR',
          channels: ['internal'],
        },
      ],
    },
  },
]

const liveActivityState: LiveActivityState = {
  title: 'Order is being packed',
  subtitle: 'Zürich branch',
  status: 'Packing',
  steps: ['Ordered', 'Packed', 'Ready for pickup'],
  currentStep: 1,
  icon: 'shippingbox',
  tint: '#2e4a62',
}

describe('contract-fixtures', () => {
  it('widgets match widgets.json', () => {
    expect(widgets).toEqual(widgetsJson)
  })

  it('LiveActivityState matches live-activity-state.json', () => {
    expect(liveActivityState).toEqual(liveActivityStateJson)
  })
})
