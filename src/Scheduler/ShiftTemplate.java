package Scheduler;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;

public class ShiftTemplate {
    private final String name;
    private final int workerNum;
    private final String type;
    private final LocalDateTimeRange range;
    private final long duration;
    private final LocalTimeRange active;

    public ShiftTemplate(String name, int workerNum, LocalDateTimeRange range, long duration){
        this.name = name;
        this.workerNum = workerNum;
        this.range = range;
        this.duration = duration;
        this.type = null;
        this.active = null;
    }
    public ShiftTemplate(String name, int workerNum, LocalDateTimeRange range, long duration, LocalTimeRange active){
        this.name = name;
        this.workerNum = workerNum;
        this.range = range;
        this.duration = duration;
        this.type = null;
        this.active = active;
    }
    public ShiftTemplate(String name, int workerNum, LocalDateTimeRange range, long duration, String type){
        this.name = name;
        this.workerNum = workerNum;
        this.range = range;
        this.duration = duration;
        this.type = type;
        this.active = null;
    }
    public ShiftTemplate(String name, int workerNum, LocalDateTimeRange range, long duration, LocalTimeRange active,
                         String type){
        this.name = name;
        this.workerNum = workerNum;
        this.range = range;
        this.duration = duration;
        this.type = type;
        this.active = active;
    }



    /**
     *
     * @return ArrayList of Shifts based on this template.
     */
    public ArrayList<Shift> genShiftList(){
        ArrayList<Shift> output = new ArrayList<Shift>();
        LocalDateTime rangeStart = range.getStart(), rangeEnd = range.getEnd();
        LocalDateTimeRange currentDateTime = new LocalDateTimeRange(rangeStart, duration);

        while (rangeEnd.isAfter(currentDateTime.getStart())){ // while we're in range
            LocalDateTime currentStart = currentDateTime.getStart();
            LocalDateTime currentEnd = currentDateTime.getEnd();
            LocalDateTime activeStart = null, activeEnd = null;

            if (active != null) { // if it has an active range, null means active throughout range.
                LocalDateTimeRange dailyActivityRange = active.genLocalDateTimeRange(currentStart);
                activeStart = dailyActivityRange.getStart();
                activeEnd = dailyActivityRange.getEnd();
            }

            if (active != null && activeStart.isAfter(currentStart)) { // if starts before active time
                // In this case I am advancing the time frame so it starts at the beginning of activity.
                // This may prove to be the wrong choice down the line.
                currentDateTime = currentDateTime.advance(currentStart.until(activeStart, ChronoUnit.HOURS));
                currentStart = currentDateTime.getStart();
                currentEnd = currentDateTime.getEnd();
            }

            if (active != null && activeEnd.isBefore(currentEnd)) //if ends after active time
                currentEnd = activeEnd;

            if (currentEnd.isAfter(rangeEnd)) //if ends after range end
                currentEnd = rangeEnd;

            if (currentStart.isBefore(currentEnd))
                output.addLast(new Shift(name, new LocalDateTimeRange(currentStart, currentEnd), workerNum, type));
                // If the start is equal to or greater than end than this shift doesn't exist, and we do not add it.

            currentDateTime = currentDateTime.advance(duration);
        }

        return output;
    }

    private static ArrayList<Shift> mergeTwoLists (ArrayList<Shift> list1, ArrayList<Shift> list2){
        if (list1.isEmpty()) return list2;
        if (list2.isEmpty()) return list1;

        int index1 = 0, index2 = 0;
        ArrayList<Shift> output = new ArrayList<Shift>();

        while (index1 < list1.size() || index2 < list2.size()){
            if (index1 == list1.size()) // added all list1 items
                output.addLast(list2.get(index2++));
            else if (index2 == list2.size()) // added all list2 items
                output.addLast(list1.get(index1++));
            else if (list1.get(index1).compareTo(list2.get(index2)) <= 0) // next item1 is before next item2
                output.addLast(list1.get(index1++));
            else // next item2 is before next item1
                output.addLast(list2.get(index2++));
        }

        return output;
    }

    private static ArrayList<Shift> mergeLists (ArrayList<ArrayList<Shift>> lists){
        int size = lists.size();
        switch (size){
            case 0:
                return new ArrayList<Shift>();
            case 1:
                return lists.getFirst();
            case 2:
                return mergeTwoLists(lists.getFirst(), lists.get(1));
            default:
                int halfPoint = lists.size() / 2;
                ArrayList<ArrayList<Shift>> half1, half2;
                half1 = new ArrayList<ArrayList<Shift>>(lists.subList(0, halfPoint));
                half2 = new ArrayList<ArrayList<Shift>>(lists.subList(halfPoint, lists.size()));
                return mergeTwoLists(mergeLists(half1), mergeLists(half2));
        }
    }

    /**
     * generate a single, unified list of sorted Shifts based on the templates provided.
     * @param templates ArrayList of shift templates
     * @return Sorted ArrayList of Shifts
     */
    public static ArrayList<Shift> genCompleteShiftList(ArrayList<ShiftTemplate> templates){
        ArrayList<ArrayList<Shift>> shifts = new ArrayList<ArrayList<Shift>>();

        for (ShiftTemplate template : templates)
            shifts.add(template.genShiftList());

        return mergeLists(shifts);
    }
}
