package Scheduler;

import Scheduler.Exceptions.ParserInputException;

import java.io.*;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;

/**
 * Method class handling writing and reading files
 */
public class Parser {
    /**
     * Deathly simple thing to return two Strings.
     */
    private static class StringTuple{
        private String first = null;
        private String second = null;
    }

    /**
     * Generate a CSV file according to the input
     * @param table Scheduler.ScheduleTable according to which the CSV will be generated.
     * @param path Output directory
     */
    public static void genCSV(ScheduleTable table, String path){
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            writer.write(table.toString());
            System.out.println("File written successfully.");
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    /**
     * Generate a CSV file according to the input
     * @param shifts ArrayList of shifts to turn into a Scheduler.ScheduleTable from which the CSV table will be made.
     * @param path Output directory
     */
    public static void genCSV(ArrayList<Shift> shifts, String path){
        ScheduleTable table = new ScheduleTable();
        table.generate(shifts);
        genCSV(table, path);
    }

    /**
     * gets a Scheduler.LocalDateTimeRange from a String
     * Each LocalDateTime has to be formatted in DateTimeFormatter.ISO_LOCAL_DATE_TIME, and they must be separated
     * by a dash (-).
     * @param line String representing a Scheduler.LocalDateTimeRange
     * @return Scheduler.LocalDateTimeRange
     */
    private static LocalDateTimeRange parseLocalDateTimeRange(String line){
        // TODO: implement some input checks in this bit.
        String[] splitString = line.split(" - ");
        LocalDateTime start = LocalDateTime.parse(splitString[0].strip());
        LocalDateTime end = LocalDateTime.parse(splitString[1].strip());
        return new LocalDateTimeRange(start, end);
    }

    private static LocalTimeRange parseLocalTimeRange(String line){
        String[] splitString = line.split("-");
        LocalTime start = LocalTime.parse(splitString[0].strip());
        LocalTime end = LocalTime.parse(splitString[1].strip());
        return new LocalTimeRange(start, end);
    }

    public static ArrayList<ShiftTemplate> getStations(String inputPath) throws ParserInputException {
        ArrayList<ShiftTemplate> output = new ArrayList<ShiftTemplate>();

        try (BufferedReader br = new BufferedReader(new FileReader(inputPath))){
            String line;
            String name=null, type=null;
            Integer workerNum=null, duration=null;
            LocalDateTimeRange range = null;
            LocalTimeRange active = null;


            while ((line = br.readLine()) != null){
                if (line.isBlank()) continue;

                String[] splitLine = line.split("=");
                String parameter = splitLine[0].strip();
//                String value = splitLine[1].strip();
                String value;
                if (splitLine.length == 2) value = splitLine[1].strip(); // has value after '='
//                else if (splitLine.length == 1) value = null; // has no value after '='
                else if (splitLine.length == 1) continue;
                else throw new ParserInputException("unexpected amount of '=' symbols");

                switch (parameter){
                    case "NAME":
                        if (name == null) name = value;
                        else{
                            if (workerNum == null || range == null || duration == null){
                                throw new ParserInputException("Station  " + name + " is missing one or more of the " +
                                        "values workerNum, range and duration.");
                            }

                            output.add(new ShiftTemplate(name, workerNum, range, duration, active, type));
                            name = value;
                            type = null;
                            workerNum = null;
                            duration = null;
                            range = null;
                            active = null;
                        }
                        break;
                    case "WORKER_NUM":
                        if (name == null) throw new ParserInputException("no Station name given");
                        workerNum = Integer.parseInt(value);
                        break;
                    case "TYPE":
                        if (name == null) throw new ParserInputException("no Station name given");
                        type = value;
                        break;
                    case "RANGE":
                        if (name == null) throw new ParserInputException("no Station name given");
                        range = parseLocalDateTimeRange(value);
                        break;
                    case "DURATION":
                        if (name == null) throw new ParserInputException("no Station name given");
                        duration = Integer.parseInt(value);
                        break;
                    case "ACTIVE":
                        if (name == null) throw new ParserInputException("no Station name given");
                        active = parseLocalTimeRange(value);
                        break;
                    default:
                        throw new ParserInputException("Encountered unknown parameter " + parameter + ".");
                }
            }
            // add last station
            if (workerNum == null || range == null || duration == null){
                throw new ParserInputException("Station " + name + " is missing one or more of the " +
                        "values workerNum, range and duration.");
            }
            output.add(new ShiftTemplate(name, workerNum, range, duration, active, type));

        }
        catch (IOException e) {
            throw new RuntimeException(e);
        }

        return output;
    }

    private static ArrayList<LocalDateTimeRange> getMultRanges(String line){
        ArrayList<LocalDateTimeRange> output = new ArrayList<LocalDateTimeRange>();

        String[] rangeStringArr = line.split(",");
        for (String s : rangeStringArr) {
            output.add(new LocalDateTimeRange(s.strip()));
        }

        return output;
    }

    private static HashMap<String, Worker> hashMapifyWorkers(ArrayList<Worker> workers){
        HashMap<String, Worker> output = new HashMap<String, Worker>();
        for (Worker worker : workers){
            output.put(worker.getName(), worker);
        }
        return output;
    }

    /**
     * Generates a like or dislike list for the given workers according to the given string map
     * @param stringMap HashMap where the key is the worker name and the value is a String array of worker names
     *                  this worker likes or dislikes.
     * @param workers ArrayList of Workers
     * @param liked if 'true' this method will add the workers specified in stringMap to the likedList.
     *              if 'false' this method will add the workers specified in stringMap to the DislikedList.
     */
    private static void addWorkersToLikedList(HashMap<String, String[]> stringMap,
                                              ArrayList<Worker> workers, boolean liked){
        // inefficient way of doing this, but I'm lazy at the moment.
        HashMap<String, Worker> workerHashMap = hashMapifyWorkers(workers);

        for (Worker worker : workers){
            if (stringMap.get(worker.getName()) == null) continue;

            for (String otherWorkerName : stringMap.get(worker.getName())){
                if (!workerHashMap.containsKey(otherWorkerName)) continue;

                Worker otherWorker = workerHashMap.get(otherWorkerName);
                if (liked) worker.addLiked(otherWorker);
                else worker.addDisliked(otherWorker);
            }
        }
    }

    public static ArrayList<Worker> getWorkers(String inputPath) throws ParserInputException{
        ArrayList<Worker> output = new ArrayList<Worker>();
        String line;

        try (BufferedReader br = new BufferedReader(new FileReader(inputPath))){
            String name=null, role=null;
            ArrayList<LocalDateTimeRange> unavailable = new ArrayList<LocalDateTimeRange>();
            LocalDateTime lastShift = null;
            HashMap<String, String[]> likeStrings = new HashMap<String, String[]>();
            HashMap<String, String[]> dislikeStrings = new HashMap<String, String[]>();

            while ((line = br.readLine()) != null) {
                if (line.isBlank()) continue;

                String[] splitLine = line.split("=");
                String parameter = splitLine[0].strip();
//                String value = splitLine[1].strip();
                String value;
                if (splitLine.length == 2) value = splitLine[1].strip(); // has value after '='
//                else if (splitLine.length == 1) value = null; // has no value after '='
                else if (splitLine.length == 1) continue;
                else throw new ParserInputException("unexpected amount of '=' symbols");

                switch (parameter){
                    case "NAME":
                        if (name == null) name = value;
                        else{
                            Worker newWorker = new Worker(name, role, lastShift);
                            for (LocalDateTimeRange range : unavailable){
                                newWorker.addUnavailable(range);
                            }
                            output.add(newWorker);

                            name = value;
                            role = null;
                            unavailable = new ArrayList<LocalDateTimeRange>();
                            lastShift = null;
                        }
                        break;
                    case "ROLE":
                        if (name == null) throw new ParserInputException("no worker name given");
                        role = value;
                        break;
                    case "UNAVAILABLE":
                        if (name == null) throw new ParserInputException("no worker name given");
                        unavailable = getMultRanges(line);
                        break;
                    case "LIKE_LIST":
                        if (name == null) throw new ParserInputException("no worker name given");
                        likeStrings.put(name, value.split(","));
                        break;
                    case "DISLIKE_LIST":
                        if (name == null) throw new ParserInputException("no worker name given");
                        dislikeStrings.put(name, value.split(","));
                        break;
                    case "LAST_SHIFT":
                        if (name == null) throw new ParserInputException("no worker name given");
                        lastShift = LocalDateTime.parse(value);
                        break;
                    default:
                        throw new ParserInputException("Encountered unknown parameter " + parameter + ".");
                }
            }

            // add last worker
            Worker newWorker = new Worker(name, role, lastShift);
            for (LocalDateTimeRange range : unavailable) {newWorker.addUnavailable(range);}
            output.add(newWorker);

            // add liked/disliked lists to all workers
            addWorkersToLikedList(likeStrings, output, true);
            addWorkersToLikedList(dislikeStrings, output, false);
        }
        catch (IOException e){
            throw new RuntimeException(e);
        }

        return output;
    }

}
