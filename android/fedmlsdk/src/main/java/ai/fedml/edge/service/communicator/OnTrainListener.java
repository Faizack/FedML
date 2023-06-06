package ai.fedml.edge.service.communicator;

import org.json.JSONException;
import org.json.JSONObject;

import ai.fedml.edge.service.communicator.message.MessageDefine;
import ai.fedml.edge.utils.LogHelper;

public interface OnTrainListener extends OnJsonReceivedListener, MessageDefine {
    @Override
    default void onJsonReceived(String topic, JSONObject jsonMsg) {
        try {
            jsonMsg.put(TOPIC, topic);
        } catch (JSONException e) {
            LogHelper.e(e, "onJsonReceived put topic failed.");
        }
        int msgType = jsonMsg.optInt(MSG_TYPE, 0);
        if(MSG_TYPE_CONNECTION_IS_READY == msgType){
            LogHelper.i("OnTrainListener %s", "FedMLDebug. handleMessageConnectionReady: " + jsonMsg);
            handleMessageConnectionReady(jsonMsg);
        } else if (MSG_TYPE_S2C_INIT_CONFIG == msgType) {
            LogHelper.i("OnTrainListener %s", "FedMLDebug. handleMessageInit: " + jsonMsg);
            handleMessageInit(jsonMsg);
        } else if (MSG_TYPE_S2C_SYNC_MODEL_TO_CLIENT == msgType) {
            LogHelper.i("OnTrainListener %s", "FedMLDebug. handleMessageReceiveModelFromServer: " + jsonMsg);
            handleMessageReceiveModelFromServer(jsonMsg);
        } else if (MSG_TYPE_S2C_CHECK_CLIENT_STATUS == msgType) {
            LogHelper.i("OnTrainListener %s", "FedMLDebug. handle_message_check_status: " + jsonMsg);
            handleMessageCheckStatus(jsonMsg);
        } else if (MSG_TYPE_S2C_FINISH == msgType) {
            LogHelper.i("OnTrainListener %s", "FedMLDebug. handle_message_finish: " + jsonMsg);
            handleMessageFinish(jsonMsg);
        }
    }

    void handleMessageConnectionReady(JSONObject jsonMsg);

    void handleMessageInit(JSONObject jsonMsg);

    void handleMessageReceiveModelFromServer(JSONObject jsonMsg);

    void handleMessageCheckStatus(JSONObject jsonMsg);

    void handleMessageFinish(JSONObject jsonMsg);
}
