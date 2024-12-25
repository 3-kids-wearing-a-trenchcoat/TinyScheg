import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.Objects;

public class LocalDateTimeRange implements Comparable<LocalDateTimeRange>{
    private final LocalDateTime start;
    private final LocalDateTime end;

    public LocalDateTimeRange(LocalDateTime start, LocalDateTime end) throws IllegalArgumentException{
        if (start.isAfter(end)) throw new IllegalArgumentException("start time is later than end time.");
        this.start = start;
        this.end = end;
    }
    public LocalDateTimeRange (LocalDateTime start, long hours){
        this.start = start;
        this.end = start.plusHours(hours);
    }
    public LocalDateTimeRange (String str){
        String[] arr = str.split("-");
        if (arr.length != 2) {throw new IllegalArgumentException("LocalDateTimeRange constructor has been" +
                " passed a string containing more or less than two dashes (-).");}
        start = LocalDateTime.parse(arr[0].strip());
        end = LocalDateTime.parse(arr[1].strip());
    }

    public boolean inRange(LocalDateTime time){
        return ((time.isAfter(start) || time.isEqual(start)) && (time.isBefore(end) || time.isEqual(end)));
    }
    public boolean inRange(LocalDateTime time, long offset){
        LocalDateTimeRange newRange = new LocalDateTimeRange(start.minusHours(offset), end.plusHours(offset));
        return newRange.inRange(time);
    }

    public boolean overlaps(LocalDateTimeRange time){return (inRange(time.start) || inRange(time.end));}
    public boolean overlaps(LocalDateTimeRange time, long offset){
        return (inRange(time.start.minusHours(offset)) || inRange(time.end.plusHours(offset)));
    }

    public boolean isBefore(LocalDateTimeRange range) {return end.isBefore(range.start);}
    public boolean isBefore(LocalDateTime time) {return end.isBefore(time);}
    public boolean isAfter(LocalDateTimeRange range) {return start.isAfter(range.end);}
    public boolean isAfter(LocalDateTime time) {return start.isAfter(time);}

    public static LocalDateTimeRange merge(LocalDateTimeRange range1, LocalDateTimeRange range2){
        LocalDateTime newStart, newEnd;
        if (range1.start.isBefore(range2.start)) {newStart = range1.start;}
        else {newStart = range2.start;}
        if (range1.end.isAfter(range2.end)) {newEnd = range1.end;}
        else {newEnd = range2.end;}
        return new LocalDateTimeRange(newStart, newEnd);
    }

    /**
     * Compares between two LocalDateTimeRange objects by comparing the start LocalDateTime
     * and then checking the end LocalDateTime iff the two start values are equal.
     * @param other the LocalDateTimeRange object to be compared.
     * @return -1 if start is before other's start OR if starts are equal and end is before other's end.
     *          1 if start is after other's start OR if starts are equal and end is after other's end.
     *          0 if both start and end are equal.
     */
    @Override
    public int compareTo(LocalDateTimeRange other) {
        if (start.isBefore(other.start)) return -1;
        if (start.isAfter(other.start)) return 1;
        // start == other.start
        if (end.isBefore(other.end)) return -1;
        if (end.isAfter(other.end)) return 1;
        // end == other.end
        return 0;
    }

    @Override
    public boolean equals(Object obj){
        if (!(obj instanceof LocalDateTimeRange)) return false;
        LocalDateTimeRange other = (LocalDateTimeRange) obj;
        return (start.isEqual(other.start) && end.isEqual(other.end));
    }

    @Override
    public int hashCode(){
        return Objects.hash(start, end);
    }

    @Override
    public String toString(){
        return start.toString() + " -> " + end.toString();
    }

    public LocalDateTime getStart() {return start;}
    public LocalDateTime getEnd() {return end;}

    public LocalDateTimeRange advance(long hours){
        return new LocalDateTimeRange(start.plusHours(hours), end.plusHours(hours));
    }

    public LocalTimeRange getLocalTimeRange(){
        return new LocalTimeRange(start.toLocalTime(), end.toLocalTime());
    }

    public class LocalDateTimeRangeTuple{
        public LocalDateTimeRange first;
        public LocalDateTimeRange second;
        public LocalDateTimeRangeTuple(LocalDateTimeRange first, LocalDateTimeRange second){
            this.first = first;
            this.second = second;
        }
    }



}
