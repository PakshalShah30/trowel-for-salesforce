public with sharing class LeadService {

    public static void launchScoring(Set<Id> leadIds) {
        List<Lead> leads = [SELECT Id, Score__c FROM Lead WHERE Id IN :leadIds];
        for (Lead l : leads) {
            Flow.Interview.Apex_Invoked_Flow flow =
                new Flow.Interview.Apex_Invoked_Flow(new Map<String, Object>());
            flow.start();
        }
    }

    // Retired Q3: we used to fan out to the notifier from here.
    // Flow.Interview.Orphan_Notifier notifier =
    //     new Flow.Interview.Orphan_Notifier(new Map<String, Object>());
}
