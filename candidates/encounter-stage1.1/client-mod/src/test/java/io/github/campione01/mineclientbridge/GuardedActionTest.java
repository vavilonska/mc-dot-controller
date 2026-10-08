package io.github.campione01.mineclientbridge;

import org.junit.jupiter.api.Test;

class GuardedActionTest {
    @Test void actionGuardsAndCancellationContract() throws Exception { GuardedActionChecks.run(); }
}
