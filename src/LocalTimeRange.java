import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

public class LocalTimeRange {
    private final LocalTime start;
    private final LocalTime end;
    private final boolean untilNextDay;

    public LocalTimeRange(LocalTime start, LocalTime end){
        this.start = start;
        this.end = end;
//        untilNextDay = start.isAfter(end);
        untilNextDay = !start.isBefore(end);
    }
    public LocalTimeRange(LocalTime start, LocalTime end, boolean untilNextDay){
        this.start = start;
        this.end = end;
        this.untilNextDay = untilNextDay;
    }

    private static boolean isEqual (LocalTime time1, LocalTime time2){
        return (time1.getHour() == time2.getHour()) && (time1.getMinute() == time2.getMinute());
    }

    public boolean inRange(LocalTime time){
        //TODO: this can and probably should be cleaned up once it's clear it's working correctly.
        if (!untilNextDay) {
            return (time.isAfter(start) || isEqual(start, time)) && (time.isBefore(end) || isEqual(end, time));
        }
        // goes past midnight
        if (time.isBefore(LocalTime.MAX) || isEqual(time, LocalTime.MAX)){ //Before midnight
            return time.isAfter(start) || isEqual(time, start);
        }
        // At or after Midnight
//        return (time.isAfter(LocalTime.MIDNIGHT) || isEqual(time, LocalTime.MIDNIGHT)) &&
//                (time.isBefore(end) || isEqual(time, end));
        return time.isBefore(end) || isEqual(time, end);
    }
    public boolean inRange(LocalTime time, boolean excludeEdges){
        if (!excludeEdges) return inRange(time);

        if (!untilNextDay) {return (time.isAfter(start)) && (time.isBefore(end));}
        // goes past midnight
        if (time.isBefore(LocalTime.MAX) || isEqual(time, LocalTime.MAX)) return time.isAfter(start);
        // At or after Midnight
        return time.isBefore(end);
    }

    public boolean contains (LocalTimeRange other){return inRange(other.start) && inRange(other.end);}
    public boolean strongContains (LocalTimeRange other) {
        return inRange(other.start, true) && inRange(other.end, true);
    }

    public boolean overlaps(LocalTimeRange other){
        return inRange(other.start) || inRange(other.end);
    }

    /**
     * Gets a new LocalTimeRange that's made by subtracting the input range from the original.
     * This method only supports subtractions which result in one continuous Range,
     * Meaning that the start time and/or end time must be contained within the subtraction range.
     * @param subtraction The range to be subtracted from the original.
     * @return Subtracted LocalTimeRange or null if the range is contained entirely within the subtraction.
     * @throws UnsupportedOperationException If the subtraction results in two separate ranges instead of one continuous range.
     */
    public LocalTimeRange minus (LocalTimeRange subtraction) throws UnsupportedOperationException{
        short containState = 0;

        if (strongContains(subtraction)) throw new UnsupportedOperationException();
        if (subtraction.inRange(start)) containState += 1;
        if (subtraction.inRange(end)) containState += 2;

        switch (containState){
            case 0: //subtraction and original range do not intersect.
                return this; //all fields are final anyway so should be fine.
            case 1: //start is in subtraction, end isn't.
                return new LocalTimeRange(subtraction.end, end);
            case 2: //start isn't in subtraction, end is.
                return new LocalTimeRange(start, subtraction.start);
            case 3: //both start and end are contained in subtraction
                return null;
            default:
                throw new UnsupportedOperationException();
        }
    }

    public LocalTime getStart() {return start;}
    public LocalTime getEnd() {return end;}
    public boolean goesToNextDay() {return untilNextDay;}

    public LocalDateTimeRange genLocalDateTimeRange (LocalDate date){
        LocalDateTime start = LocalDateTime.of(date, this.start);
        LocalDateTime end;
        if (untilNextDay) end = LocalDateTime.of(date.plusDays(1), this.end);
        else end = LocalDateTime.of(date, this.end);

        return new LocalDateTimeRange(start, end);
    }
    public LocalDateTimeRange genLocalDateTimeRange(LocalDateTime date){
        return genLocalDateTimeRange(date.toLocalDate());
    }
}
