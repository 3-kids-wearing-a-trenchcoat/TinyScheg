/**
 * Thrown to indicate some error has occurred while generating the Schedule.
 */
public class ScheduleGenerationException extends Exception{
    public ScheduleGenerationException () {
        super();
    }

    public ScheduleGenerationException (String message) {
        super (message);
    }

    public ScheduleGenerationException (Throwable cause) {
        super (cause);
    }

    public ScheduleGenerationException(String message, Throwable cause) {
        super (message, cause);
    }
}
