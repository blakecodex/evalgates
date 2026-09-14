Feature: the release gate
  The gate runs a versioned suite against the scoring service and exits
  with a code CI blocks on. It fails closed: a check it cannot run counts
  against the release, and a run that is not green never becomes the
  baseline other runs are judged by.

  Scenario: a healthy release ships
    Given the scoring service is healthy
    When the gate runs the release suite
    Then the gate exits 0
    And every check in the run passes

  Scenario: a threshold failure blocks the release
    Given the model ships with a biased intercept
    When the gate runs the release suite
    Then the gate exits 1
    And the calibration check is the one that failed

  Scenario: a regression blocks the release even when thresholds pass
    Given the scoring service is healthy
    And a baseline from a run with tighter calibration
    When the gate runs the release suite against that baseline
    Then the gate exits 2
    And the regression names the metric that got worse

  Scenario: a check the gate cannot run blocks the release
    Given a suite that points at a slice file that does not exist
    When the gate runs that suite
    Then the gate exits 3

  Scenario: a red run never becomes the baseline
    Given the model ships with a biased intercept
    When the gate runs the release suite asking to save the baseline
    Then the gate exits 1
    And no baseline file is written
