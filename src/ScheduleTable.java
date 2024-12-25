import java.util.ArrayList;
import java.util.HashMap;

public class ScheduleTable {
    private int rowNum = 0;
    private int colNum = 0;
    private HashMap<String, Integer> headerIndex = new HashMap<String, Integer>(); // indicates col for given header
    private HashMap<LocalDateTimeRange, Integer> rowIndex = new HashMap<LocalDateTimeRange, Integer>();

    private HashMap<Integer, HashMap<Integer, String>> table = new HashMap<Integer, HashMap<Integer, String>>();

    public ScheduleTable(){
        table.put(0, new HashMap<Integer, String>());
    }

    public int getRowNum() {return rowNum;}
    public int getColNum() {return colNum;}

    public String get(int row, int col){
        if (row > rowNum || col > colNum) {return null;}
        return table.get(row).get(col);
    }
    public String get(LocalDateTimeRange dateTimeRange, String shiftName){
        int row = rowIndex.get(dateTimeRange);
        int col = headerIndex.get(shiftName);
        return get(row, col);
    }

    public void set(LocalDateTimeRange  dateTime, String shiftName, String value){
        int row, col;

        if (!headerIndex.containsKey(shiftName)) {
            headerIndex.put(shiftName, ++colNum);
            table.get(0).put(colNum, shiftName);
            col = colNum;
        }
        else {col = headerIndex.get(shiftName);}

        if (!rowIndex.containsKey(dateTime)){
            rowIndex.put(dateTime, ++rowNum);
            table.put(rowNum, new HashMap<Integer, String>());
            table.get(rowNum).put(0, dateTime.toString());
            row = rowNum;
        }
        else {row = rowIndex.get(dateTime);}

        table.get(row).put(col, value);
    }
    public void generate(ArrayList<Shift> shifts){
        for (Shift shift : shifts){
            set(shift.getTimeRange(), shift.getName(), shift.getAssignedString());
        }
    }

    /**
     *
     * @return This table in CSV format
     */
    @Override
    public String toString(){
        String output = "";

        for (int i = 0; i <= rowNum; i++){
            for (int j = 0; j <= colNum; j++){
                String addition = table.get(i).get(j);
                if (addition != null)
                    output += addition;
                if (j != colNum) {output += ",";}
            }
            if (i != rowNum) {output += "\n";}
        }

        return output;
    }


}
