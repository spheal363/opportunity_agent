/** backend/schemas/calendar.py と対応。 */
export type CalendarConflict = {
  title: string;
  start_at: string;
  end_at: string;
};

export type CalendarAvailability = {
  available: boolean;
  conflicts: CalendarConflict[];
};

export type CalendarEventCreated = {
  calendar_event_id: string;
  status: string;
};
