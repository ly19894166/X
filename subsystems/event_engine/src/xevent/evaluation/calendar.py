"""Trading time arithmetic over a pre-registered, complete declared calendar."""
from datetime import timedelta
from .contracts import SettlementWindow, WINDOWS


def validate_calendar(calendar):
    from datetime import date
    offset = timedelta(minutes=calendar.session.utc_offset_minutes)
    dates = {d.trading_date for d in calendar.days} | set(calendar.closed_dates)
    start=(calendar.coverage_start+offset).date()
    end=(calendar.coverage_end+offset).date()
    needed={str(start+timedelta(days=i)) for i in range((end-start).days)}
    if dates!=needed or calendar.qualification_status!='ENGINEERING_QUALIFIED': raise ValueError('CALENDAR_UNKNOWN')
    if calendar.session.utc_offset_minutes!=480: raise ValueError('CALENDAR_UNKNOWN')
    for d in calendar.days:
        date.fromisoformat(d.trading_date)
        if any(str((a+offset).date())!=d.trading_date or str((b+offset).date())!=d.trading_date for a,b in d.intervals):
            raise ValueError('CALENDAR_DATE_MISMATCH')
        clocks=tuple(((a+offset).strftime('%H:%M:%S'),(b+offset).strftime('%H:%M:%S')) for a,b in d.intervals)
        if clocks!=(('09:30:00','11:30:00'),('13:00:00','15:00:00')): raise ValueError('CALENDAR_UNKNOWN')


def next_session(calendar, at):
    validate_calendar(calendar)
    for day in calendar.days:
        for start,end in day.intervals:
            if at < end: return max(at,start)
    raise ValueError('CALENDAR_UNKNOWN')


def trading_day(calendar, at):
    for day in calendar.days:
        if any(start <= at <= end for start,end in day.intervals): return day.trading_date
    return None


def add_minutes(calendar, at, minutes):
    validate_calendar(calendar)
    remaining=timedelta(minutes=minutes)
    for day in calendar.days:
        for start,end in day.intervals:
            start=max(start,at)
            if start>=end: continue
            if end-start>=remaining: return start+remaining
            remaining-=end-start
    raise ValueError('CALENDAR_UNKNOWN')


def windows(calendar, package_at):
    anchor=next_session(calendar,package_at)
    day=trading_day(calendar,anchor)
    i=next(i for i,d in enumerate(calendar.days) if d.trading_date==day)
    if i+3>=len(calendar.days): raise ValueError('CALENDAR_UNKNOWN')
    current,nxt,third=calendar.days[i],calendar.days[i+1],calendar.days[i+3]
    ends=(add_minutes(calendar,package_at,30),current.intervals[-1][1],
        nxt.intervals[0][0]+timedelta(minutes=5),nxt.intervals[0][0]+timedelta(minutes=30),
        nxt.intervals[-1][1],third.intervals[-1][1])
    return tuple(SettlementWindow(name=name,start=package_at,end=end,trading_date=trading_day(calendar,end))
        for name,end in zip(WINDOWS,ends))


def diagnostic_grid(calendar,start,end):
    result=[]
    for day in calendar.days:
        for a,b in day.intervals:
            t=max(a,start)
            while t<=min(b,end):
                result.append(t); t+=timedelta(minutes=1)
    return tuple(sorted(set(result)))
