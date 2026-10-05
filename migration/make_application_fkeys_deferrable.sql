-- Make foreign key constraints referencing applications(id) DEFERRABLE
-- This allows changing the application ID within a transaction using SET CONSTRAINTS ALL DEFERRED

-- user_applications.application_id
ALTER TABLE user_applications DROP CONSTRAINT IF EXISTS user_applications_application_id_fkey;
ALTER TABLE user_applications ADD CONSTRAINT user_applications_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE;

-- deployments.application_id
ALTER TABLE deployments DROP CONSTRAINT IF EXISTS deployments_application_id_fkey;
ALTER TABLE deployments ADD CONSTRAINT deployments_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE;

-- application_costs.application_id
ALTER TABLE application_costs DROP CONSTRAINT IF EXISTS application_costs_application_id_fkey;
ALTER TABLE application_costs ADD CONSTRAINT application_costs_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE;

-- billing_activities.application_id
ALTER TABLE billing_activities DROP CONSTRAINT IF EXISTS billing_activities_application_id_fkey;
ALTER TABLE billing_activities ADD CONSTRAINT billing_activities_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE;
