trigger LeadTrigger on Lead (after insert, after update) {
    LeadService.launchScoring(Trigger.newMap.keySet());
}
